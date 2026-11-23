#!/bin/bash
# ==============================================================================
# One-Command Systemd Service Installer for ANY-URL-DOWNLOADER Bot
# ==============================================================================

set -e

# Detect root / sudo privileges
if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Please run this script with sudo or as root:"
    echo "   sudo bash setup_service.sh"
    exit 1
fi

# Detect application directory and user
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SUDO_USER:-$USER}"

echo "=========================================================="
echo "🚀 Setting up any-url-bot.service"
echo "📂 App Directory: $APP_DIR"
echo "👤 Service User : $SERVICE_USER"
echo "=========================================================="

# Check if .env exists
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/.env.example" ]; then
        echo "⚠️ Warning: .env not found. Creating from .env.example..."
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
        echo "ℹ️ Please edit $APP_DIR/.env with your Telegram credentials."
    fi
fi

# Check for virtual environment python
PYTHON_EXEC="$APP_DIR/venv/bin/python"
if [ ! -f "$PYTHON_EXEC" ]; then
    echo "ℹ️ Virtual environment not found at $APP_DIR/venv."
    echo "   Creating Python virtual environment..."
    python3 -m venv "$APP_DIR/venv"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/venv"
    sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
    sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

# Write systemd service file
SERVICE_PATH="/etc/systemd/system/any-url-bot.service"
echo "📝 Writing systemd unit file to $SERVICE_PATH..."

cat > "$SERVICE_PATH" << EOF
[Unit]
Description=Any URL, HLS, Zoom & Google Drive Telegram Downloader Bot
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$PYTHON_EXEC bot.py
Restart=always
RestartSec=10
EnvironmentFile=$APP_DIR/.env

# Security Hardening
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable and restart service
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

echo "⚡ Enabling any-url-bot.service..."
systemctl enable any-url-bot.service

echo "🚀 Starting any-url-bot.service..."
systemctl restart any-url-bot.service

echo ""
echo "=========================================================="
echo "✅ any-url-bot.service installed and started successfully!"
echo "=========================================================="
echo ""
systemctl status any-url-bot.service --no-pager || true

echo ""
echo "💡 Helpful commands:"
echo "   View live logs: sudo journalctl -u any-url-bot.service -f"
echo "   Restart bot:    sudo systemctl restart any-url-bot.service"
echo "   Stop bot:       sudo systemctl stop any-url-bot.service"
echo ""
