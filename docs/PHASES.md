# Implementation Phases — July 3–5, 2026 Sprint

**July 5 is the project build deadline** — the pipeline, scripts, and automation must be complete and handoff-ready by then.  
**500K collection** continues after handoff via the continuous supervisor until `target_count` is reached.

## Timeline Overview

| Phase               | Window          | Goal                                          |
| ------------------- | --------------- | --------------------------------------------- |
| 0. Setup            | Jul 3, 0–4h     | Pipeline skeleton, first crawlers live        |
| 1. Volume           | Jul 3, 4–12h    | Scale downloads, basic validation             |
| 2. Quality          | Jul 3–4, 12–24h | Scoring + blocklists + dedup                  |
| 3. Scale & harden   | Jul 4, 0–24h    | Cloud workers, tune thresholds, stability     |
| 4. Project delivery | Jul 5, 0–24h    | Hand off runnable system, docs, manifests, QA |

Post–Jul 5: supervisor runs until 500K qualified files are collected.

---

## Phase 0: Setup (Hours 0–4)

### Objectives

- [ ] Environment provisioned (compute, storage, network)
- [ ] Pipeline config loaded and validated
- [ ] Blocklists imported (expand F500 to full list)
- [ ] First 3 crawlers operational
- [ ] Download + validate loop working end-to-end

### Tasks

1. `pip install -r requirements.txt`
2. Expand `config/blocklists/fortune500.yaml` to full 500
3. Implement `src/download/downloader.py` with retry logic
4. Implement `src/validation/file_integrity.py` + `slide_count.py`
5. Seed URL discovery from `config/sources.yaml`
6. Smoke test: 100 files through full pipeline

### Success Criteria

- 1,000+ files downloaded and validated
- Audit logs writing correctly
- Manifest CSV generates without errors

---

## Phase 1: Volume (Hours 4–12)

### Objectives

- [ ] 10+ parallel crawler workers
- [ ] Blocklist filtering active
- [ ] Basic deduplication (hash-based)

### Tasks

1. Deploy distributed download queue (Redis or cloud queue)
2. Add search-query discovery (`src/discovery/search_engines.py`)
3. Implement `src/filtering/blocklist_filter.py`
4. Implement `src/filtering/duplicate_detector.py` (content hash)
5. Rate limiting per domain
6. Progress dashboard or CLI report

### Success Criteria

- Sustained download throughput
- < 10% blocklist rejection rate (good source selection)
- Duplicate rate tracked

---

## Phase 2: Quality (Hours 12–24)

### Objectives

- [ ] Quality scoring v1 deployed
- [ ] AI exclusion check on borderline cases

### Tasks

1. Implement `src/analysis/graphics_density.py` (OpenCV)
2. Implement `src/analysis/ocr.py` (text density)
3. Implement `src/filtering/quality_scorer.py`
4. Integrate AI prompts for scoring and exclusion
5. Perceptual hash deduplication
6. Review queue for scores 60–74

### Success Criteria

- Avg quality score ≥ 65
- Acceptance rate 40–60% of validated files
- Zero F500/elite uni in random 500-sample audit

---

## Phase 3: Scale & Harden (Jul 4)

### Objectives

- [ ] Cloud-scale parallel processing
- [ ] Optimized storage and transfer
- [ ] Production-stable supervisor

### Tasks

1. Scale to 50+ download workers
2. GPU workers for vision scoring (batch inference)
3. Object storage sync (S3/Azure Blob)
4. Tune quality thresholds based on Phase 2 metrics
5. Add more seed sources from high-yield domains
6. Category tagging pass

### Success Criteria

- Pipeline stable under load
- Storage within budget cap
- Watchdog and crash recovery verified

---

## Phase 4: Project Delivery (Jul 5)

### Objectives

- [ ] Runnable pipeline handed off (scripts, config, docs)
- [ ] Master manifest CSV + Excel export working
- [ ] Delivery bundle (`scripts/deliver.py`) verified
- [ ] Final QA audit on sample batch

### Tasks

1. `src/delivery/bundle.py` — zip archives + master manifest
2. `src/delivery/manifest.py` — full CSV/Excel export
3. QA: random 1000-file manual review (on available sample)
4. Source URL reachability check
5. Delivery handoff documentation (`docs/REQUIREMENTS_COMPLIANCE.md`)

### Success Criteria

- All pipeline stages operational end-to-end
- 100% manifest coverage for qualified files
- Supervisor confirmed running toward 500K post-handoff
- QA pass rate ≥ 95% on reviewed sample

---

## Post-Handoff Collection (after Jul 5)

The continuous supervisor (`python -m scripts.run_pipeline run`) runs until **500,000** qualified files are on disk. Progress reports every 4–6 hours. Use `run_pipeline deliver` to produce updated bundles as the dataset grows.

---

## Risk Mitigation

| Risk                      | Mitigation                                                   |
| ------------------------- | ------------------------------------------------------------ |
| Source rate limiting      | Rotate IPs, respect delays, diversify sources                |
| Low acceptance rate       | Lower threshold temporarily; add more sources                |
| Storage overflow          | Compress PDFs; delete rejected raw files                     |
| Blocklist false positives | Human review queue; fuzzy match tuning                       |
| Build deadline pressure   | Prioritize runnable pipeline over collection volume by Jul 5 |
| Legal issues              | Public sources only; log all URLs; robots.txt compliance     |

---

## Standup Metrics

Report these at each phase boundary:

- Total URLs discovered
- Total downloaded / validated / accepted / rejected
- Rejection breakdown by reason code
- Current acceptance rate and avg quality score
- Storage used (GB)
- Top 10 source domains by yield
- Blockers and next actions
