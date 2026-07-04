# Presentation Dataset Pipeline

Large-scale automated collection of **~6,000,000** high-quality PPT/PPTX/PDF presentation files for AI training.

**Target:** 6M files in **12 hours** (~500K/hour, ~139/sec sustained)  
**Default mode:** `turbo` (scale) — web sources only, full compliance gates, optimized I/O

## Deploy on DigitalOcean (no Docker)

Simple **systemd** deployment — runs until **6M** files, resumes after crashes. Qualified files are stored in **PostgreSQL**.

```bash
# On a fresh Ubuntu 24.04 droplet (as root):
git clone <your-repo-url> /tmp/pipeline-src
cd /tmp/pipeline-src
sudo bash deploy/digitalocean/setup.sh
# Set DATABASE_URL in /opt/presentation-dataset-pipeline/.env
sudo nano /mnt/pipeline-data/bulk_urls.txt
sudo systemctl start presentation-pipeline
sudo deploy/digitalocean/status.sh
```

Full guide: [deploy/digitalocean/DEPLOY.md](deploy/digitalocean/DEPLOY.md)

## Quick Start (local)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Collect until 6M (turbo scale mode — default)
python -m scripts.run_pipeline run --fresh

# Progress / delivery
python -m scripts.run_pipeline status
python -m scripts.run_pipeline deliver
```

Feed URLs aggressively — discovery is the usual bottleneck:

```bash
# One http(s) presentation URL per line
# data/bulk_urls.txt
```

## Scale design (6M / 12h)

| Concern | Approach |
|---------|----------|
| Progress | O(1) counter (`data/state/qualified_count.json`) — no full-tree scans |
| Dedupe | Content-hash only (O(1)); perceptual hash does not scale to millions |
| Scoring | Lightweight (no OCR/CV) — still enforces structure/quality thresholds |
| URL queue | Streaming claim — never loads the full queue into memory |
| Manifests | Streaming CSV; Excel only when under Excel’s ~1M row limit |
| Delivery | Sharded ZIPs (10K files each) under `data/delivery/shards/` |
| Throughput | 256 download workers, 64 score workers, 20K URLs/batch |

Required rate is logged every batch. If you fall behind, add more URLs or machines.

## Commands

| Command | Purpose |
|---------|---------|
| `run` | Collect until 6M (default `--mode turbo`) |
| `run --mode fast` | Lower parallelism |
| `run --mode synthetic` | Stress test only — writes `data/synthetic/`, not delivery |
| `status` / `deliver` / `report` / `purge` | Ops |

## Rules

- **Web only** — `http(s)` sources; no local files in `qualified/`
- **Real files** — openable PPT/PPTX/PDF with ≥5 slides
- Auto-export on goal: reports, master manifest, delivery shards

## License

Internal use — verify source licensing before redistribution.
