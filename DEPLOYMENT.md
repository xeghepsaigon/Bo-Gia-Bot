# 🚀 Deployment Guide - DigitalOcean

## Option 1: DigitalOcean App Platform (Recommended - Easy)

### Step 1: Push code lên GitHub
```bash
cd ~/Projects/Bo-Gia-Bot
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/Bo-Gia-Bot.git
git push -u origin main
```

### Step 2: Setup DigitalOcean Account
1. Đăng ký tại https://cloud.digitalocean.com
2. Tạo GitHub Personal Access Token:
   - GitHub Settings → Developer settings → Personal access tokens
   - Select scopes: `repo`, `read:org`
   - Copy token

### Step 3: Deploy trên DigitalOcean App Platform
1. Login DigitalOcean → Apps
2. Click "Create App"
3. Select "GitHub" → Authorize & select `Bo-Gia-Bot` repo
4. Configure:
   - **Name**: bo-gia-bot
   - **Branch**: main
   - **Source Type**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Run Command**: `python3 bot2.py`
   - **Port**: 5000

### Step 4: Set Environment Variables
1. App Platform → Settings → Environment
2. Add variables:
```
GEMINI_API_KEY=your_gemini_key_here
TELEGRAM_TOKEN=your_telegram_token_here
HERE_API_KEY=your_here_api_key_here
WEBHOOK_URL=https://bo-gia-bot-[random].ondigitalocean.app/webhook
FLASK_PORT=5000
```

3. Get full App URL từ:
   - App Platform → App Info → Live App
   - Format: `https://[app-name]-[random].ondigitalocean.app`

### Step 5: Update Telegram Bot Webhook
```python
# Chạy local:
import requests

WEBHOOK_URL = "https://bo-gia-bot-[random].ondigitalocean.app/webhook"
TELEGRAM_TOKEN = "your_token_here"

response = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
    json={"url": WEBHOOK_URL}
)
print(response.json())
```

### Step 6: Deploy
1. Click "Deploy"
2. Wait 2-3 minutes
3. Check logs: App → Logs

---

## Option 2: DigitalOcean Droplet (Manual - More Control)

### Step 1: Create Droplet
1. DigitalOcean → Create → Droplets
2. Choose:
   - **Image**: Ubuntu 22.04
   - **Size**: $4/month (512MB RAM, 1 CPU)
   - **Region**: Singapore (SGP1)
   - **Auth**: SSH key

### Step 2: SSH vào Droplet
```bash
ssh root@your_droplet_ip
```

### Step 3: Install Dependencies
```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx supervisor
```

### Step 4: Clone Repository
```bash
git clone https://github.com/YOUR_USERNAME/Bo-Gia-Bot.git /var/www/bo-gia-bot
cd /var/www/bo-gia-bot
```

### Step 5: Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 6: Setup Environment Variables
```bash
cp .env.example .env
nano .env
# Edit với API keys thật
```

### Step 7: Setup Gunicorn (Production Server)
```bash
pip install gunicorn
```

### Step 8: Setup Supervisor (Auto restart)
```bash
cat > /etc/supervisor/conf.d/bo-gia-bot.conf << EOF
[program:bo-gia-bot]
directory=/var/www/bo-gia-bot
command=/var/www/bo-gia-bot/venv/bin/gunicorn --workers 2 --bind 0.0.0.0:5000 bot2:app
autostart=true
autorestart=true
stderr_logfile=/var/log/bo-gia-bot.err.log
stdout_logfile=/var/log/bo-gia-bot.out.log
EOF

supervisorctl reread
supervisorctl update
supervisorctl start bo-gia-bot
```

### Step 9: Setup Nginx (Reverse Proxy)
```bash
cat > /etc/nginx/sites-available/bo-gia-bot << EOF
server {
    listen 80;
    server_name your_domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

ln -s /etc/nginx/sites-available/bo-gia-bot /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

### Step 10: Setup SSL (Let's Encrypt)
```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your_domain.com
```

### Step 11: Update Webhook
```python
WEBHOOK_URL = "https://your_domain.com/webhook"
# Cập nhật .env
```

### Step 12: Restart Bot
```bash
supervisorctl restart bo-gia-bot
```

---

## ✅ Kiểm Tra Deployment

### 1. Check Health Endpoint
```bash
curl https://your_app_url.com/
# Output: Bot is running
```

### 2. Check Logs
**App Platform**: App → Logs
**Droplet**: 
```bash
supervisorctl tail bo-gia-bot
tail -f /var/log/bo-gia-bot.out.log
```

### 3. Test Bot
- Gửi tin nhắn tới bot qua Telegram
- Kiểm tra response

---

## 🔧 Troubleshooting

**Bot không nhận tin nhắn:**
```bash
# Check webhook status
curl https://api.telegram.org/bot[TOKEN]/getWebhookInfo
```

**500 Error:**
```bash
# Check environment variables
env | grep TELEGRAM_TOKEN
```

**Port bị dùng:**
```bash
lsof -i :5000
kill -9 [PID]
```

---

## 📊 Monitoring (Optional)

Thêm logging:
```python
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Bot started")
```

---

**Recommend: App Platform (Option 1) - Dễ nhất, không cần config server!** 🚀
