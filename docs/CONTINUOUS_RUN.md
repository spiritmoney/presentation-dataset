# Continuous Run Guide

The pipeline supervisor runs batches in a loop until `target_count` qualified files are on disk.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  scripts.run_pipeline run  (ContinuousRunner)            │
│  ┌────────┐ ┌────────┐ ┌──────────┐ ┌───────┐ ┌────────┐ │
│  │discover│→│download│→│validate  │→│filter │→│ score  │ │
│  └────────┘ └────────┘ └──────────┘ └───────┘ └────────┘ │
│       → dedupe → package → report (per batch)              │
└──────────────────────────────────────────────────────────┘
```

State is persisted to `data/state/pipeline_state.json` after each stage and on a 60s timer.

## Start

```bash
# Default fast compliant mode — runs until 500K
python -m scripts.run_pipeline run

# Turbo throughput
python -m scripts.run_pipeline run --mode turbo

# With watchdog (auto-restart on crash)
nohup ./scripts/watchdog.sh > data/logs/watchdog.log 2>&1 &
```

## Monitor

```bash
python -m scripts.run_pipeline status
cat data/state/heartbeat.json
cat data/reports/progress_latest.json
```

## Pause and Resume

```bash
# Start in stoppable mode
python -m scripts.run_pipeline run --allow-stop
# Ctrl+C saves checkpoint

# Resume
python -m scripts.run_pipeline run --resume
```

## Stall Handling

If no new qualified files appear for `stall_timeout_sec` (default 30 min), the health monitor clears the current batch and triggers rediscovery.

If `max_stagnant_batches` consecutive batches add zero files, the supervisor pauses — add URL sources (`data/bulk_urls.txt`) or lower `--target-count`.

## Synthetic Dev Mode

```bash
python -m scripts.run_pipeline run --mode synthetic --target-count 50000
```

Skips web discovery/download; generates PPTX locally. **Not delivery-compliant.**
