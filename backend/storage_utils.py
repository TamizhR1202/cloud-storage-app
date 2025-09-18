# storage_utils.py
import os
import boto3
import botocore
from urllib.parse import urlparse
import smtplib
from email.message import EmailMessage

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET")

# boto3 clients; if running on EC2 with IAM role, credentials come from instance role.
s3 = boto3.client("s3", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)

def upload_fileobj_to_s3(fileobj, key, content_type=None):
    ExtraArgs = {}
    if content_type:
        ExtraArgs["ContentType"] = content_type
    s3.upload_fileobj(fileobj, S3_BUCKET, key, ExtraArgs=ExtraArgs)
    return key

def generate_presigned_get_url(key, expires_in=3600):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )

def delete_s3_object(key):
    s3.delete_object(Bucket=S3_BUCKET, Key=key)

def list_user_prefix(prefix):
    # prefix is like 'users/{user_id}/'
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    contents = resp.get("Contents", []) if resp.get("KeyCount",0)>0 else []
    return [c["Key"] for c in contents]

def send_sms_via_sns(phone_number, message):
    # phone_number must be in E.164 format: +91xxxxxxxxxx
    sns.publish(PhoneNumber=phone_number, Message=message)

def send_email_via_smtp(to_email, subject, body):
    import os
    SMTP_SERVER = os.environ.get("SMTP_SERVER")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
