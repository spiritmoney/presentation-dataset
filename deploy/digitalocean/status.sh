#!/usr/bin/env bash
# Quick status on the droplet (run with sudo).
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/presentation-dataset-pipeline}"
APP_USER="${APP_USER:-pipeline}"

echo "=== systemd ==="
systemctl is-active presentation-pipeline 2>/dev/null || echo "inactive"
systemctl status presentation-pipeline --no-pager -l 2>/dev/null | head -15 || true

echo ""
echo "=== pipeline ==="
sudo -u "$APP_USER" -H bash -c "
    cd '$INSTALL_DIR'
    source .venv/bin/activate
    python -m scripts.run_pipeline status
"

DATA_DIR=$(grep '^DATA_DIR=' "$INSTALL_DIR/.env" 2>/dev/null | cut -d= -f2- || echo "./data")
echo ""
echo "=== disk ($DATA_DIR) ==="
df -h "$DATA_DIR" 2>/dev/null || df -h /
