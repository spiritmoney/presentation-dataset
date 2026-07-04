# Requirements Compliance Matrix

This document maps the **Revised Delivery Requirements** (PDF) and **AI Training Dataset Project Brief** (DOCX) to the pipeline implementation.

**Project build deadline:** July 5, 2026 — pipeline, scripts, and automation delivered by this date  
**Collection target:** 500,000 PPT/PPTX/PDF files — supervisor runs until goal is reached (not tied to July 5)

## 1. Delivery Requirements

| Requirement             | Acceptance Criteria                  | Status          | Implementation                              |
| ----------------------- | ------------------------------------ | --------------- | ------------------------------------------- |
| PPTX or PDF format      | Opens without corruption             | **Implemented** | `src/validation/slide_count.py`             |
| Legacy PPT support      | Converted when LibreOffice available | **Implemented** | `src/validation/ppt_convert.py`             |
| Unique file names       | No duplicates in delivery            | **Implemented** | `{batch_id}_{seq:06d}{ext}` naming          |
| Source URL traceability | URL in audit log                     | **Implemented** | Mandatory in filter; manifest + audit JSONL |
| Batch tracking          | Batch ID on every file               | **Implemented** | `batch_id` in manifest and filenames        |
| Public availability     | Public Access Status = PASS          | **Implemented** | `src/validation/source_url.py`              |
| Minimum 5 slides/pages  | ≥ 5 slides                           | **Implemented** | Validate stage + config                     |
| No maximum slide limit  | Long decks accepted                  | **Implemented** | No upper bound                              |
| Source URL reachability | URL status recorded                  | **Implemented** | `source_status` + `public_access_status`    |
| Audit record per file   | Audit entry exists                   | **Implemented** | `src/metadata/audit_log.py`                 |

## 2. Source Exclusion Requirements

| Excluded Source                            | Status          | Implementation                              |
| ------------------------------------------ | --------------- | ------------------------------------------- |
| Fortune 500 companies                      | **Implemented** | `config/blocklists/fortune500.yaml`         |
| Elite U.S. universities                    | **Implemented** | `config/blocklists/elite_universities.yaml` |
| Prestigious research centers / think tanks | **Implemented** | `config/blocklists/think_tanks.yaml`        |
| Future blocklists                          | **Implemented** | Add YAML under `config/blocklists/`         |

## 3. Metadata Preservation

All mandatory and preferred fields are captured in the CSV/Excel manifest:

| Field                            | Status          | Location                            |
| -------------------------------- | --------------- | ----------------------------------- |
| Source URL                       | **Implemented** | manifest, audit, sidecar            |
| Source Domain                    | **Implemented** | `download_domain`                   |
| Download URL                     | **Implemented** | `download_url`                      |
| Original File Name               | **Implemented** | `original_filename`                 |
| Collection / Download Timestamps | **Implemented** | ISO timestamps in manifest          |
| Publication Date                 | **Implemented** | Extracted from PPTX/PDF properties  |
| Author / Organization / Title    | **Implemented** | `src/metadata/document_metadata.py` |
| Language                         | **Implemented** | From document or default `en`       |
| File Size / Format               | **Implemented** | `file_size_bytes`, `file_type`      |
| Tags / Categories                | **Implemented** | `tags`                              |
| Crawl / Processing Metadata      | **Implemented** | JSON columns in manifest            |

## 4. Document Quality Requirements

| Requirement                  | Status          | Implementation                |
| ---------------------------- | --------------- | ----------------------------- |
| Graphics-rich content        | **Implemented** | Visual element scoring        |
| Reject text-heavy lectures   | **Implemented** | `TEXT_HEAVY`                  |
| Reject generic templates     | **Implemented** | `GENERIC_TEMPLATE`            |
| Reject marketing-only decks  | **Implemented** | `MARKETING_ONLY`              |
| Reject quote collections     | **Implemented** | `QUOTE_COLLECTION`            |
| Reject minimal-content decks | **Implemented** | `MINIMAL_CONTENT`             |
| Reject image galleries       | **Implemented** | `IMAGE_GALLERY`               |
| Reject blurry / poor scans   | **Implemented** | `BLURRY` via OpenCV Laplacian |
| OCR for scanned PDFs         | **Implemented** | PyMuPDF OCR text pass         |
| Consistent quality threshold | **Implemented** | `min_quality_score: 60`       |

## 5. Automation & Deliverables (Project Brief)

| Deliverable                   | Status          | Implementation                                            |
| ----------------------------- | --------------- | --------------------------------------------------------- |
| ~500K qualified files         | **Implemented** | Continuous supervisor until `target_count`                |
| Automated scraping            | **Implemented** | Archive.org, direct URLs, bulk URL lists (http/s only)    |
| AI / CV / OCR scoring         | **Implemented** | `quality_scorer.py`, `visual_clarity.py`, PDF OCR         |
| Duplicate detection           | **Implemented** | Content hash + perceptual hash (`deduplication/index.py`) |
| robots.txt compliance         | **Implemented** | `src/download/robots.py`                                  |
| CSV manifest                  | **Implemented** | Per-batch + `MASTER_MANIFEST.csv`                         |
| Excel manifest                | **Implemented** | Per-batch `.xlsx` + `MASTER_MANIFEST.xlsx`                |
| Delivery ZIP bundle           | **Implemented** | `scripts/deliver.py`                                      |
| Collection scripts            | **Implemented** | `scripts/discover.py` … `scripts/package.py`              |
| Progress updates (4–6 hr)     | **Implemented** | `scripts/report.py`, supervisor heartbeat                 |
| July 5 project build deadline | **Configured**  | `pipeline.project_deadline` — system ready by this date   |
| Collection toward 500K        | **Implemented** | Runs after handoff until goal; no fixed dataset deadline  |

## Verification

```bash
pip install -r requirements.txt
python -m scripts.run_pipeline run --batch BATCH-FULL --fresh --target-count 6 --allow-stop
python -m scripts.run_pipeline run --mode turbo --target-count 100
python -m scripts.run_pipeline report
python -m scripts.run_pipeline deliver
```

### Speed modes (all gates enforced unless `--mode synthetic`)

| Command                             | Mode           | Compliance                               |
| ----------------------------------- | -------------- | ---------------------------------------- |
| `run_pipeline run`                  | fast (default) | Full — parallel downloads, 5K URLs/batch |
| `run_pipeline run --mode turbo`     | turbo          | Full — 128 downloads, 10K URLs/batch     |
| `run_pipeline run --mode synthetic` | stress only    | **Not for delivery**                     |

Outputs:

- `data/qualified/{batch_id}/` — qualified files
- `data/manifests/{batch_id}.csv` + `.xlsx` — batch manifest
- `data/manifests/MASTER_MANIFEST.csv` + `.xlsx` — full dataset manifest
- `data/delivery/presentation_dataset_*.zip` — delivery bundle
- `data/audit/{batch_id}.jsonl` — audit trail
- `data/reports/progress_latest.json` — progress snapshot
