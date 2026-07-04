"""Discover presentation URLs from Common Crawl CDX index."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.validation.source_url import is_web_source_url

logger = logging.getLogger(__name__)

USER_AGENT = "PresentationDatasetBot/0.1 (+research; common-crawl)"
COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
PRESENTATION_EXTENSIONS = (".pdf", ".pptx", ".ppt")
DEFAULT_PATTERNS = ("*.pptx", "*.ppt", "*.pdf")


def _extension_from_url(url: str) -> str:
    from pathlib import Path
    from urllib.parse import urlparse

    return Path(urlparse(url).path).suffix.lower().lstrip(".")


def list_crawl_indexes(client: httpx.Client) -> list[str]:
    resp = client.get(COLLINFO_URL)
    resp.raise_for_status()
    return [row["id"] for row in resp.json()]


def _worker_page(base_page: int, worker_id: int, worker_count: int) -> int:
    if worker_count <= 1:
        return base_page
    return base_page * worker_count + worker_id


def discover_common_crawl(
    *,
    patterns: list[str] | None = None,
    crawl_id: str | None = None,
    page: int = 0,
    limit: int = 5000,
    worker_id: int = 0,
    worker_count: int = 1,
    client: httpx.Client | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Query Common Crawl CDX for presentation URLs.

    Returns (rows, state_patch) where state_patch updates crawl cursor.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=90, headers={"User-Agent": USER_AGENT})

    patterns = patterns or list(DEFAULT_PATTERNS)
    discovered: list[dict[str, Any]] = []
    state: dict[str, Any] = {
        "page": page,
        "crawl_id": crawl_id,
        "pattern_index": 0,
    }

    try:
        indexes = list_crawl_indexes(client)
        if not indexes:
            logger.warning("Common Crawl: no indexes available")
            return [], state

        active_crawl = crawl_id if crawl_id in indexes else indexes[0]
        state["crawl_id"] = active_crawl
        cdx_page = _worker_page(page, worker_id, worker_count)

        for pattern in patterns:
            if len(discovered) >= limit:
                break
            try:
                resp = client.get(
                    f"https://index.commoncrawl.org/{active_crawl}-index",
                    params={
                        "url": pattern,
                        "output": "json",
                        "limit": limit,
                        "page": cdx_page,
                        "filter": "status:200",
                    },
                )
                resp.raise_for_status()
            except Exception as e:
                logger.warning("Common Crawl CDX failed %s page=%s: %s", pattern, cdx_page, e)
                continue

            for line in resp.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                url = (row.get("url") or "").strip()
                if not is_web_source_url(url):
                    continue
                if not url.lower().endswith(PRESENTATION_EXTENSIONS):
                    continue

                discovered.append(
                    {
                        "url": url,
                        "source": "common_crawl",
                        "source_query": pattern,
                        "category": "common_crawl",
                        "file_type": _extension_from_url(url),
                        "mime_type": row.get("mime", ""),
                        "metadata": {
                            "crawl_id": active_crawl,
                            "timestamp": row.get("timestamp", ""),
                            "status": row.get("status", ""),
                            "digest": row.get("digest", ""),
                            "length": row.get("length", ""),
                        },
                    }
                )
                if len(discovered) >= limit:
                    break

        state["page"] = page + 1
        return discovered, state
    finally:
        if owns_client and client is not None:
            client.close()
