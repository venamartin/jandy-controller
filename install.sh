#!/bin/bash

# Pre-flight Checks
if [ "$EUID" -eq 0 ]; then
  echo "Please do not run this script as root (do not use sudo ./install.sh or sudo bash install.sh)."
  echo "The script will prompt for sudo access when needed."
  exit 1
fi

echo "==============================================="
echo "   Jandy RS-485 Controller - Auto Installer    "
echo "==============================================="

# Install dependencies
echo "=> Checking dependencies (nano, curl)..."
if ! command -v nano &> /dev/null || ! command -v curl &> /dev/null; then
    echo "Installing missing dependencies..."
    sudo apt update && sudo apt install -y nano curl
fi

# Install uv if missing
echo "=> Checking for uv..."
if ! command -v uv &> /dev/null; then
    if [ -f "$HOME/.local/bin/uv" ]; then
        UV_PATH="$HOME/.local/bin/uv"
    elif [ -f "$HOME/.cargo/bin/uv" ]; then
        UV_PATH="$HOME/.cargo/bin/uv"
    else
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        
        # Check standard install locations
        if [ -f "$HOME/.local/bin/uv" ]; then
            UV_PATH="$HOME/.local/bin/uv"
        elif [ -f "$HOME/.cargo/bin/uv" ]; then
            UV_PATH="$HOME/.cargo/bin/uv"
        else
            echo "Error: Could not locate uv after installation."
            exit 1
        fi
    fi
else
    UV_PATH=$(command -v uv)
fi
echo "Using uv at: $UV_PATH"

# Sync dependencies
echo "=> Syncing Python dependencies..."
$UV_PATH sync

# Config setup
echo "=> Checking configuration..."
if [ ! -f "config.yaml" ]; then
    echo "Creating config.yaml from example..."
    cp config.example.yaml config.yaml
    echo "Press ENTER to open nano and configure your hardware settings (press Ctrl+X, Y, Enter to save)."
    read -r
    nano config.yaml
else
    echo "config.yaml already exists. Skipping configuration."
fi

# Systemd Service Generation
echo "=> Generating systemd service..."
SERVICE_FILE="/tmp/jandy.service"
CURRENT_DIR=$(pwd)
CURRENT_USER=$USER

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Jandy RS-485 Controller
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$UV_PATH run uvicorn web:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Installing service to /etc/systemd/system/jandy.service..."
sudo mv $SERVICE_FILE /etc/systemd/system/jandy.service
sudo systemctl daemon-reload
sudo systemctl enable jandy
sudo systemctl restart jandy

echo "==============================================="
echo " Installation Complete!"
echo " The Jandy controller is now running in the background."
echo " To view the live logs, run:"
echo "   sudo journalctl -fu jandy"
echo "==============================================="
