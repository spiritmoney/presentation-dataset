# AI Prompt — Metadata Extraction

Extract all available metadata from a presentation file and its source context.

## Input
- Source URL
- HTTP response headers (if available)
- HTML page context (if downloaded from web)
- File properties (name, size, format)
- Document internal properties (PPT/PDF metadata fields)
- First-slide text (title slide)

## Output Format (JSON only)

```json
{
  "document_title": "",
  "author": "",
  "organization": "",
  "publication_date": "YYYY-MM-DD or null",
  "language": "en",
  "original_filename": "",
  "source_url": "",
  "download_url": "",
  "source_domain": "",
  "file_format": "pptx",
  "file_size_bytes": 0,
  "slide_count": 0,
  "description": "",
  "keywords": [],
  "copyright": "",
  "creation_date": "",
  "modification_date": ""
}
```

## Rules
- Never fabricate metadata — use `null` for unknown fields
- `source_url` is mandatory — if not provided in input, set to `null` and flag
- Prefer document-internal title over filename
- Normalize dates to ISO 8601
- Extract organization from author field, footer text, or source domain if not explicit
