#!/usr/bin/env bash
# One-command install on Ubuntu 24.04 (DigitalOcean droplet). No Docker.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo bash deploy/digitalocean/setup.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/presentation-dataset-pipeline}"
APP_USER="${APP_USER:-pipeline}"
VOLUME_MOUNT="${VOLUME_MOUNT:-/mnt/pipeline-data}"

echo "==> Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    git rsync curl \
    libgl1 libglib2.0-0 \
    postgresql-client \
    >/dev/null

echo "==> Creating user: $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --home-dir "$INSTALL_DIR" --shell /bin/bash "$APP_USER"
fi

echo "==> Installing code to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.env' \
    "$REPO_ROOT/" "$INSTALL_DIR/"

chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/deploy/digitalocean/"*.sh

echo "==> Python virtualenv"
sudo -u "$APP_USER" python3 -m venv "$INSTALL_DIR/.venv"
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# Data directory — prefer attached DO Volume
if mountpoint -q "$VOLUME_MOUNT" 2>/dev/null; then
    DATA_DIR="$VOLUME_MOUNT"
    echo "==> Using volume: $DATA_DIR"
else
    DATA_DIR="/var/lib/presentation-pipeline/data"
    echo "==> No volume at $VOLUME_MOUNT — using $DATA_DIR"
    echo "    (Attach a DO Volume and re-run setup, or symlink bulk_urls there)"
fi

mkdir -p "$DATA_DIR"/{logs,state,staging,qualified,manifests,delivery,audit,raw,rejected}
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    echo "==> Creating .env"
    DATABASE_URL="${DATABASE_URL:-}"
    cat >"$INSTALL_DIR/.env" <<EOF
DATA_DIR=$DATA_DIR
TARGET_COUNT=6000000
PIPELINE_MODE=turbo
LOG_LEVEL=INFO
STORAGE_BACKEND=postgres
DATABASE_URL=$DATABASE_URL
EOF
    chown "$APP_USER:$APP_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
else
    echo "==> Keeping existing .env"
fi

# Placeholder for URL feed
BULK="$DATA_DIR/bulk_urls.txt"
if [[ ! -f "$BULK" ]]; then
    touch "$BULK"
    chown "$APP_USER:$APP_USER" "$BULK"
    echo "# One http(s) URL per line (.ppt .pptx .pdf)" >"$BULK"
fi

echo "==> Installing systemd service"
cp "$INSTALL_DIR/deploy/digitalocean/presentation-pipeline.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable presentation-pipeline.service

echo ""
echo "=============================================="
echo " Install complete"
echo "=============================================="
echo "  Code:     $INSTALL_DIR"
echo "  Data:     $DATA_DIR"
echo "  URLs:     $BULK"
echo ""
echo " Next steps:"
echo "  1. Set DATABASE_URL in $INSTALL_DIR/.env (DO Managed PostgreSQL)"
echo "  2. Add presentation URLs to bulk_urls.txt"
echo "  3. sudo systemctl start presentation-pipeline"
echo "  4. sudo journalctl -u presentation-pipeline -f"
echo ""
echo " Status:"
echo "  sudo $INSTALL_DIR/deploy/digitalocean/status.sh"
echo "=============================================="
