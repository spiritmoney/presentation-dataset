# Deploy on DigitalOcean (no Docker)

Runs the pipeline as a **systemd** service until **6,000,000** qualified web files are collected. Restarts on crash; stops cleanly when the goal is reached.

## TL;DR (3 commands after droplet + volume)

```bash
sudo bash deploy/digitalocean/setup.sh
# Edit .env: set DATABASE_URL to your DO Managed PostgreSQL connection string
sudo nano /opt/presentation-dataset-pipeline/.env
sudo nano /mnt/pipeline-data/bulk_urls.txt    # add http(s) URLs, one per line
sudo systemctl start presentation-pipeline && sudo journalctl -u presentation-pipeline -f
```

Qualified presentation **binaries** are stored in **PostgreSQL** (`BYTEA`). Staging downloads still use disk briefly; manifests and delivery ZIPs export from the database.

## PostgreSQL setup

### Option A — DigitalOcean Managed Database (recommended)

1. DO Console → **Databases** → **Create** → PostgreSQL 16
2. Same region/VPC as the droplet; note the connection string
3. On the droplet, set in `/opt/presentation-dataset-pipeline/.env`:

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://doadmin:PASSWORD@HOST:25060/defaultdb?sslmode=require
```

4. Schema is applied automatically on first run (`qualified_files`, `dedupe_hashes`).

### Option B — PostgreSQL on the same droplet

```bash
sudo apt install -y postgresql
sudo -u postgres createuser pipeline --createdb
sudo -u postgres createdb pipeline -O pipeline
# set password, then DATABASE_URL=postgresql://pipeline:PASS@localhost:5432/pipeline
```

For 6M files, use **Managed PostgreSQL** with a large storage plan — corpus size can reach multiple TB.

## 1. Create a droplet

1. DigitalOcean → **Create** → **Droplets**
2. Image: **Ubuntu 24.04 LTS**
3. Plan (minimum for scale):
   - **16 vCPU / 32 GB RAM** (CPU-Optimized or General Purpose)
   - Prefer **Premium Intel/AMD** if available
4. Add SSH key, create droplet

### Storage (important)

6M presentations can need **many terabytes**. Attach a **Volume**:

1. **Volumes** → create (start large; you can expand later)
2. Attach to the droplet
3. On the droplet:

```bash
# Find device (often /dev/sda or /dev/disk/by-id/scsi-...)
lsblk
sudo mkfs.ext4 -F /dev/disk/by-id/scsi-0DO_Volume_pipeline-data
sudo mkdir -p /mnt/pipeline-data
sudo mount /dev/disk/by-id/scsi-0DO_Volume_pipeline-data /mnt/pipeline-data
echo '/dev/disk/by-id/scsi-0DO_Volume_pipeline-data /mnt/pipeline-data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

`setup.sh` uses `/mnt/pipeline-data` automatically when that mount exists.

## 2. Install the app

SSH in as root (or use `sudo`):

```bash
# Option A — from git
export REPO_URL="https://github.com/YOUR_ORG/presentation-dataset-pipeline.git"
export BRANCH="master"
git clone --branch "$BRANCH" "$REPO_URL" /tmp/pipeline-src
cd /tmp/pipeline-src
sudo bash deploy/digitalocean/setup.sh

# Option B — upload this repo (scp/rsync), then:
cd /path/to/presentation-dataset-pipeline
sudo bash deploy/digitalocean/setup.sh
```

This installs Python, creates user `pipeline`, venv, `.env` (`TARGET_COUNT=6000000`, `PIPELINE_MODE=turbo`), and enables the systemd unit.

## 3. Feed URLs (required for throughput)

```bash
sudo -u pipeline nano /var/lib/presentation-pipeline/data/bulk_urls.txt
# or on the volume:
sudo -u pipeline nano /mnt/pipeline-data/bulk_urls.txt
```

One `http(s)` presentation URL per line (`.ppt`, `.pptx`, `.pdf`).

## 4. Start collection

```bash
sudo systemctl start presentation-pipeline
sudo systemctl status presentation-pipeline
journalctl -u presentation-pipeline -f
```

Check progress anytime:

```bash
sudo -u pipeline -H bash -c 'cd /opt/presentation-dataset-pipeline && source .venv/bin/activate && python -m scripts.run_pipeline status'
```

## 5. How it runs “normally” until 6M

| Piece | Behavior |
|-------|----------|
| `run-until-goal.sh` | Loops `run_pipeline run --mode turbo --resume` |
| Crash / OOM / exit | Sleeps 30s, resumes from checkpoint |
| Goal reached | Exits 0; systemd does not keep restarting a successful finish |
| systemd `Restart=on-failure` | Recovers if the wrapper itself dies |

Do **not** pass `--fresh` in production (wipes checkpoint).

## 6. Ops commands

```bash
# Stop / start
sudo systemctl stop presentation-pipeline
sudo systemctl start presentation-pipeline

# Logs
journalctl -u presentation-pipeline -f
journalctl -u presentation-pipeline --since "1 hour ago"

# Manual deliver (also auto-runs on goal)
sudo -u pipeline -H bash -c 'cd /opt/presentation-dataset-pipeline && source .venv/bin/activate && python -m scripts.run_pipeline deliver'

# Update code
cd /opt/presentation-dataset-pipeline
sudo -u pipeline git pull
sudo -u pipeline /opt/presentation-dataset-pipeline/.venv/bin/pip install -r requirements.txt
sudo systemctl restart presentation-pipeline
```

## 7. Firewall / networking

Outbound HTTPS must be open (Archive.org and other sources). No inbound ports required for the pipeline itself.

```bash
# Optional: allow only SSH
ufw allow OpenSSH
ufw enable
```

## Layout on the droplet

```
/opt/presentation-dataset-pipeline/     # code + .venv + .env
/var/lib/presentation-dataset-pipeline/data/   # or /mnt/pipeline-data (URLs, logs, staging)
PostgreSQL (managed)                  # qualified file binaries + dedupe index
  qualified_files                     # BYTEA content + JSONB manifest
  dedupe_hashes
```

Service unit: `/etc/systemd/system/presentation-pipeline.service`

## 8. Scaling beyond one droplet (optional)

6M files in 12 hours needs **millions of URLs** and heavy disk/CPU. You can shard work:

1. Split `bulk_urls.txt` into N parts (e.g. `bulk_urls_01.txt` … `bulk_urls_N.txt`).
2. Launch N droplets, each with its own volume.
3. On droplet *i*, set in `.env` before start:
   - `DATA_DIR=/mnt/pipeline-data`
   - Unique `TARGET_COUNT` per shard (e.g. `6000000 / N`), **or** run independent counts and merge deliveries later.
4. Point each droplet at its URL shard (copy to `bulk_urls.txt` on that machine).

Merge final `delivery/` ZIP shards from each droplet when all shards finish.
