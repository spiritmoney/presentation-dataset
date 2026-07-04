#!/usr/bin/env bash
# Run pipeline until 6M goal — resume after crashes. Used by systemd.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/presentation-dataset-pipeline}"
cd "$INSTALL_DIR"
source .venv/bin/activate

# shellcheck disable=SC1091
[[ -f .env ]] && set -a && source .env && set +a

export PIPELINE_MODE="${PIPELINE_MODE:-turbo}"
PAUSE_SEC="${RESTART_PAUSE_SEC:-30}"

log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"; }

goal_reached() {
    python -c "
from src.config import Settings, get_target_count
from src.supervisor.state import StateManager, RunStatus
from src.supervisor.progress import count_qualified_files

s = Settings()
state_path = s.data_dir / 'state' / 'pipeline_state.json'
state = StateManager(state_path).load()
target = state.target_count if state else get_target_count()
if state and state.status == RunStatus.GOAL_REACHED:
    raise SystemExit(0)
count = count_qualified_files(s.data_dir / 'qualified')
raise SystemExit(0 if count >= target else 1)
"
}

log "Pipeline starting (mode=$PIPELINE_MODE, target from config/.env)"

while true; do
    if goal_reached; then
        log "Goal already reached — exiting."
        exit 0
    fi

    log "Running collection (resume from checkpoint)..."
    set +e
    python -m scripts.run_pipeline run --mode "$PIPELINE_MODE" --resume
    code=$?
    set -e

    if goal_reached; then
        log "Goal reached — done."
        exit 0
    fi

    log "Pipeline exited (code=$code). Resuming in ${PAUSE_SEC}s..."
    sleep "$PAUSE_SEC"
done
