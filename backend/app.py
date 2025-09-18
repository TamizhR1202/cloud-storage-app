# app.py
import os
import uuid
import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from dotenv import load_dotenv
from storage_utils import (
    upload_fileobj_to_s3, generate_presigned_get_url,
    delete_s3_object, list_user_prefix,
    send_sms_via_sns, send_email_via_smtp
)

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "devsecret")
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "jwt-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///./myapp.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PRESIGNED_EXPIRES"] = int(os.environ.get("PRESIGNED_EXPIRES", 3600))

db = SQLAlchemy(app)
jwt = JWTManager(app)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), unique=True, nullable=False)  # chosen username/ID
    name = db.Column(db.String(150))
    gender = db.Column(db.String(20))
    email = db.Column(db.String(150), unique=True, nullable=True)
    mobile = db.Column(db.String(30), unique=True, nullable=True)
    password_hash = db.Column(db.String(256))
    is_verified = db.Column(db.Boolean, default=False)
    otp = db.Column(db.String(10), nullable=True)
    otp_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# --- Utility ---
def generate_otp():
    return str(uuid.uuid4().int)[:6]  # 6-digit-ish (string)

def user_s3_prefix(user_id):
    return f"users/{user_id}/"

# --- Routes ---
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/register", methods=["POST"])
def register():
    """
    JSON body: { "user_id","name","gender","email","mobile","password" }
    Sends OTP (sms or email based on OTP_METHOD env)
    """
    data = request.get_json() or {}
    required = ["user_id", "name", "password"]
    for r in required:
        if r not in data:
            return jsonify({"error": f"missing {r}"}), 400

    user_id = data["user_id"]
    if User.query.filter((User.user_id==user_id) | (User.email==data.get("email")) | (User.mobile==data.get("mobile"))).first():
        return jsonify({"error":"user/email/mobile already exists"}), 400

    u = User(
        user_id=user_id,
        name=data.get("name"),
        gender=data.get("gender"),
        email=data.get("email"),
        mobile=data.get("mobile"),
    )
    u.set_password(data["password"])
    otp = generate_otp()
    u.otp = otp
    u.otp_expires = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    db.session.add(u)
    db.session.commit()

    # send OTP
    otp_method = os.environ.get("OTP_METHOD", "sns")  # sns or email
    if otp_method == "sns" and u.mobile:
        try:
            send_sms_via_sns(u.mobile, f"Your OTP code: {otp}")
        except Exception as e:
            return jsonify({"error": "failed to send SMS", "detail": str(e)}), 500
    elif otp_method == "email" and u.email:
        try:
            send_email_via_smtp(u.email, "Your OTP", f"Your OTP code: {otp}")
        except Exception as e:
            return jsonify({"error": "failed to send email", "detail": str(e)}), 500
    else:
        # fallback: return OTP for dev/testing (DO NOT do in production)
        return jsonify({"message":"OTP sent (dev)", "otp": otp}), 200

    return jsonify({"message":"otp_sent"}), 200

@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    """
    JSON: { "user_id", "otp" }
    """
    data = request.get_json() or {}
    user_id = data.get("user_id")
    otp = data.get("otp")
    if not user_id or not otp:
        return jsonify({"error":"missing user_id or otp"}), 400
    u = User.query.filter_by(user_id=user_id).first()
    if not u:
        return jsonify({"error":"user not found"}), 404
    if u.otp != otp:
        return jsonify({"error":"invalid otp"}), 400
    if u.otp_expires < datetime.datetime.utcnow():
        return jsonify({"error":"otp expired"}), 400
    u.is_verified = True
    u.otp = None
    u.otp_expires = None
    db.session.commit()
    return jsonify({"message":"verified"}), 200

@app.route("/login", methods=["POST"])
def login():
    """
    JSON: { "user_id", "password" }
    Returns JWT access token
    """
    data = request.get_json() or {}
    user_id = data.get("user_id")
    password = data.get("password")
    if not user_id or not password:
        return jsonify({"error":"missing credentials"}), 400
    u = User.query.filter_by(user_id=user_id).first()
    if not u or not u.check_password(password):
        return jsonify({"error":"invalid credentials"}), 401
    if not u.is_verified:
        return jsonify({"error":"account not verified"}), 403
    token = create_access_token(identity=u.user_id)
    return jsonify({"access_token": token, "user": {"user_id": u.user_id, "name": u.name}}), 200

# File endpoints
@app.route("/upload", methods=["POST"])
@jwt_required()
def upload():
    """
    Multipart form upload: field 'file'
    Auth: Bearer JWT
    Stored to S3 under prefix users/{user_id}/uploads/{uid}_{filename}
    """
    current_user = get_jwt_identity()
    if "file" not in request.files:
        return jsonify({"error":"no file part"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error":"no selected file"}), 400
    unique = uuid.uuid4().hex
    key = f"{user_s3_prefix(current_user)}uploads/{unique}_{f.filename}"
    try:
        upload_fileobj_to_s3(f, key, content_type=f.content_type)
    except Exception as e:
        return jsonify({"error":"upload failed", "detail": str(e)}), 500
    return jsonify({"message":"uploaded","key":key}), 201

@app.route("/list", methods=["GET"])
@jwt_required()
def list_files():
    current_user = get_jwt_identity()
    prefix = user_s3_prefix(current_user)
    try:
        keys = list_user_prefix(prefix)
    except Exception as e:
        return jsonify({"error":"list failed", "detail": str(e)}), 500
    return jsonify({"files": keys}), 200

@app.route("/download", methods=["GET"])
@jwt_required()
def download():
    """
    Query param: ?key=users/{user_id}/uploads/...
    Returns presigned URL (only if the requested key belongs to user)
    """
    current_user = get_jwt_identity()
    key = request.args.get("key")
    if not key:
        return jsonify({"error":"missing key"}), 400
    # security: ensure key starts with user's prefix
    if not key.startswith(user_s3_prefix(current_user)):
        return jsonify({"error":"access denied"}), 403
    try:
        url = generate_presigned_get_url(key, expires_in=app.config["PRESIGNED_EXPIRES"])
    except Exception as e:
        return jsonify({"error":"failed to create url", "detail": str(e)}), 500
    return jsonify({"url": url}), 200

@app.route("/delete", methods=["DELETE"])
@jwt_required()
def delete():
    current_user = get_jwt_identity()
    data = request.get_json() or {}
    key = data.get("key")
    if not key:
        return jsonify({"error":"missing key"}), 400
    if not key.startswith(user_s3_prefix(current_user)):
        return jsonify({"error":"access denied"}), 403
    try:
        delete_s3_object(key)
    except Exception as e:
        return jsonify({"error":"delete failed", "detail": str(e)}), 500
    return jsonify({"message":"deleted"}), 200

# --- Bootstrap DB route (dev only) ---
@app.route("/_init_db", methods=["POST"])
def _init_db():
    # Danger: dev only
    db.create_all()
    return jsonify({"message":"db created"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
