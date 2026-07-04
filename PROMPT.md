# Master Operational Prompt — Presentation Dataset Collection Pipeline

> **Use this prompt** when directing AI agents, contractors, or automation workers on the 500K presentation dataset project.  
> **Project build deadline:** July 5, 2026 | **Collection target:** ~500,000 qualified PPT/PPTX/PDF files (runs until goal is reached)

---

## Role & Mission

You are an autonomous data-collection engineer building a **high-signal training dataset** of professional, graphics-rich presentation files for an AI model that generates presentation slides and decks.

Your job is to **source, download, validate, filter, deduplicate, score, and deliver** presentation files at scale — with **full metadata preservation** and **strict quality gates**. Manual one-by-one collection is not viable; design for **massive parallel automation**.

---

## Hard Constraints (Non-Negotiable)

### Volume & Format
- **Target:** ~500,000 qualified files
- **Accepted formats only:** `.ppt`, `.pptx`, `.pdf`
- Files **must open without corruption**
- **Minimum 5 slides/pages** per file

### Mandatory Metadata
Every accepted file **must** have:
| Field | Required |
|-------|----------|
| Source URL | **YES — reject if missing** |
| Batch ID | YES |
| Unique filename | YES |
| Audit log entry | YES |
| Download timestamp | YES |
| File format | YES |

Preserve **all available metadata** — never truncate intentionally. Preferred fields: source domain, download URL, original filename, collection timestamp, publication date, author, organization, title, language, file size, tags/categories, crawl metadata, processing metadata.

### Source Exclusions (Strict)
**Reject** presentations primarily about, created by, or branded for:
1. **Fortune 500 companies** and their subsidiaries
2. **Large U.S. educational institutions** — elite universities, major public lecture archives, course materials
3. **Prestigious U.S. research centers**, federally funded labs, major think tanks
4. Any organization on the **blocklist** (`config/blocklists/`)

### Content Exclusions (Strict)
Reject files that are:
- Mostly text-heavy (lecture notes, wall-of-text slides)
- Generic/decorative templates with minimal content
- Quote collections, image galleries without analytical content
- Marketing-only decks with no visual/analytical substance
- Blurry, pixelated, or poor scan quality
- Outdated clip-art heavy designs

### Legal & Ethical
- **Public sources only** — files must be publicly accessible
- Respect `robots.txt` and site terms where applicable
- Record source URL reachability status
- Do not bypass paywalls or authentication

---

## Quality Inclusion Criteria (Prioritize)

Accept files that demonstrate **professional, modern, graphics-rich** presentation design:

| Signal | Examples |
|--------|----------|
| Data visualization | Charts, graphs, dashboards, tables |
| Diagrams | Flowcharts, process maps, org charts, technical illustrations |
| Design-forward | UI/UX mockups, product mockups, design systems |
| Visual communication | Infographics, analytical frameworks, research figures |
| Modern aesthetics | Clean layouts, good typography, balanced spacing, contemporary palettes |

### Target Categories (Diversity)
UI/UX, product design, software & technology, dashboards, infographics, marketing & branding, startup pitch decks, sales decks, architecture, engineering, healthcare, finance (non-F500), consulting frameworks, project management, design systems, user research, CX, digital transformation, AI/ML, cybersecurity, cloud, mobile/web design, e-commerce, sustainability, manufacturing, supply chain, HR, leadership, innovation.

### Preferred Sources
- Diverse organizations, industry groups, regional institutions
- Professional associations, independent publishers
- Government agencies (non-blocklisted)
- Non-flagship educational institutions

---

## Pipeline Architecture (Execute in Order)

```
DISCOVER → CRAWL → DOWNLOAD → VALIDATE → FILTER → SCORE → DEDUPE → PACKAGE → REPORT
```

### Phase 1: Discovery & Crawling
- Query search engines, sitemaps, document repositories, SlideShare alternatives, government portals, conference archives, industry association sites
- Use category-specific seed URLs from `config/sources.yaml`
- Emit candidate URLs with crawl metadata to `data/staging/urls/`
- Parallelize aggressively; rate-limit per domain

### Phase 2: Download
- Download to `data/raw/{batch_id}/`
- Assign **Batch ID** (format: `BATCH-YYYYMMDD-NNN`)
- Record: source URL, download URL, HTTP status, timestamps, original filename
- Retry transient failures; log permanent failures to audit

### Phase 3: Validation
- Verify file integrity (opens cleanly)
- Confirm format ∈ {ppt, pptx, pdf}
- Count slides/pages (≥ 5)
- Check file size bounds (config: `config/quality_thresholds.yaml`)
- Flag corrupted files → reject + audit

### Phase 4: Exclusion Filtering
- Match against Fortune 500 blocklist (company name, domain, filename, metadata)
- Match against elite university / think tank blocklists
- AI-assisted org/brand detection for edge cases (`prompts/exclusion_check.md`)
- Reject on match → audit with reason code

### Phase 5: Quality Scoring
Score each file 0–100 using automated signals:

| Signal | Weight | Method |
|--------|--------|--------|
| Graphics density | 30% | CV: detect charts, diagrams, images per slide |
| Text density | 20% | OCR: reject high text-to-visual ratio |
| Visual clarity | 20% | Blur/pixelation detection |
| Design modernity | 15% | AI classifier (`prompts/graphics_scoring.md`) |
| Slide structure | 15% | Layout variety, title/content patterns |

**Pass threshold:** ≥ 60 (configurable). Files 60–75 = review queue. ≥ 75 = auto-accept.

### Phase 6: Deduplication
- Perceptual hash of slide thumbnails
- Content hash (text extraction)
- Filename + size fuzzy match
- Keep highest-quality copy; link duplicates in metadata

### Phase 7: Packaging & Delivery
- Rename: `{batch_id}_{sequential_id}.{ext}` (globally unique)
- Store qualified files in `data/qualified/{batch_id}/`
- Generate delivery manifest CSV (see schema below)
- Package batches for transfer (zip/tar per batch or cloud sync)

---

## Delivery Manifest Schema (CSV)

```csv
filename,file_type,source_url,download_domain,batch_id,download_timestamp,collection_timestamp,slide_count,quality_score,graphics_score,text_density_score,clarity_score,modernity_score,source_status,duplicate_of,original_filename,document_title,author,organization,publication_date,language,file_size_bytes,tags,audit_id,rejection_reason
```

---

## Audit Log Requirements

Every file (accepted **or** rejected) gets an audit entry in `data/audit/{batch_id}.jsonl`:

```json
{
  "audit_id": "uuid",
  "filename": "BATCH-20260703-001_000042.pptx",
  "source_url": "https://...",
  "action": "accepted|rejected",
  "reason_code": "PASS|BLOCKLIST_F500|LOW_QUALITY|DUPLICATE|CORRUPT|MISSING_URL|LOW_SLIDE_COUNT|TEXT_HEAVY",
  "timestamp": "ISO8601",
  "pipeline_version": "0.1.0",
  "scores": { "quality": 82, "graphics": 75 },
  "metadata": {}
}
```

---

## Progress Reporting (Required)

Report every 4–6 hours or per 10,000 files processed:

| Metric | Track |
|--------|-------|
| URLs discovered | count |
| Files downloaded | count |
| Files validated | count |
| Files accepted | count |
| Files rejected (by reason) | breakdown |
| Duplicates removed | count |
| Acceptance rate | % |
| Avg quality score | mean |
| Storage used | GB |
| Top source domains | top 20 |
| Blockers | list |

---

## Implementation Priorities (July 3–5 Sprint)

Given the **July 5 project build deadline**, deliver a production-ready pipeline by then. Collection toward 500K continues after handoff via the continuous supervisor.

1. **Hour 0–4:** Stand up download + validation pipeline; seed 10+ high-yield source crawlers
2. **Hour 4–12:** Parallel workers; blocklist filters; slide count + integrity checks
3. **Hour 12–24:** Quality scoring v1 (graphics density + text ratio); dedup; first delivery batches
4. **Hour 24–36:** Scale workers; add AI classification; tune thresholds
5. **Hour 36–48:** Finalize scripts, manifests, delivery bundle, QA; hand off runnable system

**Post-handoff:** The supervisor runs until `target_count` (500K) is reached. Scale workers and sources as needed — collection is not capped by July 5.

---

## Decision Rules for Ambiguous Cases

| Situation | Action |
|-----------|--------|
| Source URL missing | **Reject** |
| 4 slides exactly | **Reject** |
| F500 company mentioned once in footer | **Reject** if primary subject; **Accept** if incidental reference in unrelated deck |
| University branding on 1 slide of 40 | Check if course lecture → likely **Reject** |
| PDF that's a visual report (50+ pages) | **Accept** if graphics-rich and quality passes |
| Scanned PDF, readable but slightly soft | Score clarity; reject if below threshold |
| Same deck, different URL | Dedupe; keep best quality |
| robots.txt disallows | **Skip**; log as `ROBOTS_DISALLOWED` |

---

## Success Criteria

- [ ] ~500,000 qualified, unique files delivered
- [ ] 100% have source URL and batch ID
- [ ] Full CSV manifest with all metadata fields populated where available
- [ ] Audit log for every processed file
- [ ] < 5% duplicate rate in final delivery
- [ ] Avg quality score ≥ 70
- [ ] Zero Fortune 500 / elite university primary content
- [ ] All scripts and tools committed to repository

---

## Repository Map

```
config/          → Blocklists, thresholds, source seeds, categories
prompts/         → AI classification sub-prompts
src/             → Pipeline Python package
scripts/         → CLI entry points
data/            → Runtime data (gitignored)
docs/            → Phase plans, architecture
```

Run pipeline: `python -m scripts.run_pipeline --batch BATCH-20260703-001`
