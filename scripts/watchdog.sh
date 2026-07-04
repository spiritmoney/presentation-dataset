# Watchdog — restarts the supervisor if it crashes or stops before goal is reached.
# Usage: ./scripts/watchdog.sh
# Run in background: nohup ./scripts/watchdog.sh > data/logs/watchdog.log 2>&1 &

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
MAX_RESTARTS_PER_HOUR="${MAX_RESTARTS_PER_HOUR:-120}"
LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"

restarts=0
hour_start=$(date +%s)

log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"
}

goal_reached() {
    $PYTHON -c "
from src.config import Settings, get_target_count
from src.supervisor.state import StateManager, RunStatus
from src.supervisor.progress import count_qualified_files
s = Settings()
m = StateManager(s.data_dir / 'state' / 'pipeline_state.json')
state = m.load()
if state and state.status.value == 'goal_reached':
    exit(0)
count = count_qualified_files(s.data_dir / 'qualified')
target = state.target_count if state else get_target_count()
exit(0 if count >= target else 1)
" 2>/dev/null
}

while true; do
    if goal_reached; then
        log "Goal reached — watchdog exiting."
        exit 0
    fi

    now=$(date +%s)
    if (( now - hour_start > 3600 )); then
        restarts=0
        hour_start=$now
    fi

    if (( restarts >= MAX_RESTARTS_PER_HOUR )); then
        log "ERROR: Too many restarts ($restarts/hour). Waiting 5 minutes."
        sleep 300
        restarts=0
        hour_start=$(date +%s)
        continue
    fi

    log "Starting pipeline (restart #$restarts)..."
    $PYTHON -m scripts.run_pipeline run 2>&1 | tee -a "$LOG_DIR/supervisor.log" || true

    if goal_reached; then
        log "Goal reached after supervisor exit."
        exit 0
    fi

    restarts=$((restarts + 1))
    log "Supervisor exited before goal. Restarting in ${CHECK_INTERVAL}s..."
    sleep "$CHECK_INTERVAL"
done
