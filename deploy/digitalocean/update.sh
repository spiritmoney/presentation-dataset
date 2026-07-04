#!/usr/bin/env bash
# Update /opt install from a git clone (e.g. /tmp/pipeline-src). Run as root.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo bash deploy/digitalocean/update.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/presentation-dataset-pipeline}"
APP_USER="${APP_USER:-pipeline}"

echo "==> Updating from $REPO_ROOT to $INSTALL_DIR"
rsync -a \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '__pycache__' \
    --exclude '.env' \
    "$REPO_ROOT/" "$INSTALL_DIR/"

chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/deploy/digitalocean/"*.sh

echo "==> Refreshing Python deps"
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

echo "==> Done. Restart collectors:"
echo "  WORKER_COUNT=2 bash $INSTALL_DIR/deploy/digitalocean/run-collect-workers.sh"
