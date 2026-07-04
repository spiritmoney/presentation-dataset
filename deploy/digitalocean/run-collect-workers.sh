#!/usr/bin/env bash
# Run N parallel URL collectors on one droplet (Common Crawl + search → PostgreSQL).
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/presentation-dataset-pipeline}"
WORKER_COUNT="${WORKER_COUNT:-4}"
PAUSE_SEC="${COLLECT_PAUSE_SEC:-5}"

cd "$INSTALL_DIR"
source .venv/bin/activate
[[ -f .env ]] && set -a && source .env && set +a

echo "Starting $WORKER_COUNT URL collection workers (staggered)..."

pids=()
for ((i=0; i<WORKER_COUNT; i++)); do
    sleep "$i"
    WORKER_ID="$i" WORKER_COUNT="$WORKER_COUNT" \
        python -m scripts.run_pipeline collect --pause-sec "$PAUSE_SEC" &
    pids+=($!)
    echo "  worker $i pid=${pids[-1]}"
done

echo "Workers running. Press Ctrl+C to stop all."
trap 'kill "${pids[@]}" 2>/dev/null || true; exit 0' INT TERM

# Keep running until all workers exit (workers retry on 503 — should not crash)
wait "${pids[@]}" || true
echo "All workers stopped."
