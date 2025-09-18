#!/bin/bash
set -euo pipefail

APP_DIR=/opt/myapp
DOMAIN=YOUR_DOMAIN
BUCKET=YOUR_BUCKET
REGION=us-east-1

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx unzip build-essential libssl-dev libffi-dev python3-dev curl

# copy files to APP_DIR
sudo mkdir -p $APP_DIR
sudo cp -r /home/ubuntu/MyStorageApp/backend/* $APP_DIR/
cd $APP_DIR

# setup venv
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# systemd service
sudo cp /home/ubuntu/MyStorageApp/deploy/gunicorn.service /etc/systemd/system/gunicorn.service
sudo systemctl daemon-reload
sudo systemctl start gunicorn
sudo systemctl enable gunicorn

# nginx config
sudo cp /home/ubuntu/MyStorageApp/deploy/nginx_myapp.conf /etc/nginx/sites-available/myapp
sudo ln -sf /etc/nginx/sites-available/myapp /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
