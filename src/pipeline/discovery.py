"""Shared discovery for compliant web collection modes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.config import get_config_dir, load_yaml_config
from src.crawlers.archive_org import discover_archive_org
from src.crawlers.common_crawl import discover_common_crawl
from src.crawlers.url_queue import append_urls, claim_batch, pending_count
from src.crawlers.web_search import discover_web_search
from src.validation.source_url import is_web_source_url, queue_row_is_web

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def _discovery_flags() -> dict[str, Any]:
    cfg = load_yaml_config(get_config_dir() / "pipeline.yaml").get("discovery", {})
    return {
        "enable_archive_org": bool(cfg.get("enable_archive_org", True)),
        "enable_common_crawl": bool(cfg.get("enable_common_crawl", True)),
        "enable_web_search": bool(
            cfg.get("enable_web_search", cfg.get("enable_duckduckgo", True))
        ),
        "common_crawl_limit": int(cfg.get("common_crawl_limit", 10000)),
        "web_search_results_per_query": int(cfg.get("web_search_results_per_query", 30)),
        "web_search_max_per_discover": int(cfg.get("web_search_max_per_discover", 500)),
        "web_search_follow_landing_pages": int(cfg.get("web_search_follow_landing_pages", 10)),
    }


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
    web_search_results_per_query: int | None = None,
    web_search_max_per_discover: int | None = None,
) -> int:
    """Discover public http(s) URLs and append to the global work queue.

    Sources (automatic, no bulk_urls.txt required):
    - Web search (DuckDuckGo) using config/sources.yaml search_queries
    - Archive.org using archive_queries
  Optional:
    - direct_urls and bulk_urls.txt
    """
    flags = _discovery_flags()
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

    if flags["enable_common_crawl"]:
        import os

        cc_path = data_dir / "state" / "common_crawl_page.json"
        cc_state = {"page": 0, "crawl_id": None}
        if cc_path.exists():
            try:
                cc_state = json.loads(cc_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        patterns = sources.get("common_crawl_patterns") or ["*.pptx", "*.ppt", "*.pdf"]
        worker_id = int(os.environ.get("WORKER_ID", "0"))
        worker_count = max(1, int(os.environ.get("WORKER_COUNT", "1")))
        try:
            hits, new_cc = discover_common_crawl(
                patterns=patterns,
                crawl_id=cc_state.get("crawl_id"),
                page=int(cc_state.get("page", 0)),
                limit=flags["common_crawl_limit"],
                worker_id=worker_id,
                worker_count=worker_count,
            )
            for row in hits:
                row["discovered_at"] = _now_iso()
                discovered.append(row)
            cc_path.parent.mkdir(parents=True, exist_ok=True)
            cc_path.write_text(json.dumps(new_cc), encoding="utf-8")
            if hits:
                logger.info("Common Crawl discovered %d URLs for file queue", len(hits))
        except Exception as e:
            logger.warning("Common Crawl discovery failed: %s", e)

    if flags["enable_web_search"]:
        search_queries = sources.get("search_queries", [])
        if search_queries:
            offset_path = data_dir / "state" / "web_search_offset.json"
            offset = 0
            if offset_path.exists():
                try:
                    offset = int(json.loads(offset_path.read_text(encoding="utf-8")).get("offset", 0))
                except Exception:
                    offset = 0
            per_query = web_search_results_per_query or flags["web_search_results_per_query"]
            max_search = web_search_max_per_discover or flags["web_search_max_per_discover"]
            try:
                hits = discover_web_search(
                    search_queries,
                    results_per_query=per_query,
                    max_total=max_search,
                    query_offset=offset,
                    follow_landing_pages=flags["web_search_follow_landing_pages"],
                )
                for row in hits:
                    row["discovered_at"] = _now_iso()
                    discovered.append(row)
                offset_path.parent.mkdir(parents=True, exist_ok=True)
                offset_path.write_text(
                    json.dumps({"offset": offset + max(1, len(search_queries) // 4)}),
                    encoding="utf-8",
                )
                if hits:
                    logger.info("Web search discovered %d URLs", len(hits))
            except Exception as e:
                logger.warning("Web search discovery failed: %s", e)

    archive_queries = sources.get("archive_queries", [])
    if flags["enable_archive_org"] and archive_queries:
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
            if hits:
                logger.info("Archive.org discovered %d URLs", len(hits))
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
