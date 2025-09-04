#!/usr/bin/env bash
set -euo pipefail

PM=""
if command -v dnf >/dev/null 2>&1; then PM=dnf; fi
if command -v yum >/dev/null 2>&1; then PM=yum; fi

if [ -z "${PM}" ]; then
  echo "Unsupported system"
  exit 1
fi

sudo ${PM} -y update
sudo ${PM} -y install docker git || true
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not installed"
  exit 1
fi
sudo ${PM} -y install docker-compose-plugin || true

sudo systemctl enable --now docker

if ! groups "$USER" | grep -q docker; then
  sudo usermod -aG docker "$USER" || true
fi

if ! swapon --show | grep -q "/swapfile"; then
  sudo fallocate -l 1G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  if ! grep -q "/swapfile" /etc/fstab; then
    echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
fi

if [ ! -f .env ]; then
  echo "GEMINI_API_KEY=" >> .env
  echo "GEMINI_MODEL=gemini-2.0-flash" >> .env
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f docker-compose.dev.yml up -d --build
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f docker-compose.dev.yml up -d --build
else
  echo "docker compose is not available"
  exit 1
fi

# --- Nginx for frontend + API proxy on port 80 ---
sudo ${PM} -y install nginx || true
sudo systemctl enable --now nginx || true

# Copy static frontend
sudo mkdir -p /usr/share/nginx/html
if [ -d frontend ]; then
  sudo rsync -a --delete frontend/ /usr/share/nginx/html/
fi

# Configure proxy to backend at localhost:8000
sudo mkdir -p /etc/nginx/conf.d
sudo tee /etc/nginx/conf.d/quiz.conf >/dev/null <<'NGINX'
server {
  listen 80 default_server;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
NGINX

sudo nginx -t && sudo systemctl reload nginx || true

echo "Done. If this is your first run, log out and back in for docker group to apply."

