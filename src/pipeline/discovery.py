"""Shared discovery for compliant web collection modes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.config import get_config_dir, load_yaml_config
from src.crawlers.archive_org import discover_archive_org
from src.crawlers.url_queue import append_urls, claim_batch, pending_count
from src.validation.source_url import is_web_source_url, queue_row_is_web

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def refill_global_queue(
    data_dir: Path,
    urls_dir: Path,
    *,
    archive_rows: int = 100,
    archive_files_per_item: int = 3,
    archive_max: int = 2000,
) -> int:
    """Discover public http(s) URLs and append to the global work queue.

    Local seeds and file:// paths are never queued.
    """
    sources = load_yaml_config(get_config_dir() / "sources.yaml")
    discovered: list[dict[str, Any]] = []

    for item in sources.get("direct_urls", []):
        url = item.get("url", "")
        if is_web_source_url(url) and any(
            url.lower().endswith(ext) for ext in PRESENTATION_EXTENSIONS
        ):
            discovered.append(
                {
                    "url": url,
                    "source_query": "direct_url",
                    "category": item.get("category", "web"),
                    "discovered_at": _now_iso(),
                    "document_title": item.get("title", ""),
                }
            )

    archive_queries = sources.get("archive_queries", [])
    if archive_queries:
        page_path = data_dir / "state" / "archive_page.json"
        page_num = 1
        if page_path.exists():
            page_num = json.loads(page_path.read_text(encoding="utf-8")).get("page", 1)
        try:
            with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
                hits = discover_archive_org(
                    archive_queries,
                    client=client,
                    rows_per_query=archive_rows,
                    max_files_per_item=archive_files_per_item,
                    max_total=archive_max,
                    page=page_num,
                )
                for row in hits:
                    row["discovered_at"] = _now_iso()
                    discovered.append(row)
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(json.dumps({"page": page_num + 1}), encoding="utf-8")
        except Exception as e:
            logger.warning("Archive.org discovery failed: %s", e)

    bulk_file = data_dir / "bulk_urls.txt"
    if bulk_file.exists():
        for line in bulk_file.read_text(encoding="utf-8").splitlines():
            url = line.strip()
            if (
                is_web_source_url(url)
                and any(url.lower().endswith(ext) for ext in PRESENTATION_EXTENSIONS)
            ):
                discovered.append(
                    {
                        "url": url,
                        "source_query": "bulk_urls",
                        "category": "bulk",
                        "discovered_at": _now_iso(),
                    }
                )

    discovered = [row for row in discovered if queue_row_is_web(row)]

    if discovered:
        return append_urls(urls_dir, discovered)
    return 0


def claim_urls_for_batch(
    urls_dir: Path,
    batch_id: str,
    count: int,
) -> list[dict]:
    claimed = claim_batch(urls_dir, batch_id, count)
    return [row for row in claimed if queue_row_is_web(row)]


def pending_global_urls(urls_dir: Path) -> int:
    return pending_count(urls_dir)
