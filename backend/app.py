from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr
import random
import smtplib
from email.message import EmailMessage

app = FastAPI()

# In-memory store for demo; replace with DB
users_db = {}
otp_store = {}

# SMTP Email config
SMTP_EMAIL = "your_email@gmail.com"
SMTP_PASSWORD = "your_app_password"

class RegisterModel(BaseModel):
    email: EmailStr
    password: str

class VerifyOTPModel(BaseModel):
    email: EmailStr
    otp: int

@app.post("/register")
def register(data: RegisterModel):
    if data.email in users_db:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Generate OTP
    otp = random.randint(100000, 999999)
    otp_store[data.email] = {"otp": otp, "password": data.password}

    # Send email
    msg = EmailMessage()
    msg.set_content(f"Your OTP is: {otp}")
    msg['Subject'] = "Your OTP Code"
    msg['From'] = SMTP_EMAIL
    msg['To'] = data.email

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)

    return {"message": "OTP sent to your email"}

@app.post("/verify_otp")
def verify_otp(data: VerifyOTPModel):
    record = otp_store.get(data.email)
    if record and record["otp"] == data.otp:
        users_db[data.email] = {"password": record["password"]}
        del otp_store[data.email]
        return {"message": "Registration successful"}
    raise HTTPException(status_code=400, detail="Invalid OTP")
