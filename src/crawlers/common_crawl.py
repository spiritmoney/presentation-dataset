"""Discover presentation URLs from Common Crawl CDX index."""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import httpx

from src.validation.source_url import is_web_source_url

logger = logging.getLogger(__name__)

USER_AGENT = "PresentationDatasetBot/0.1 (+research; common-crawl)"
COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
PRESENTATION_EXTENSIONS = (".pdf", ".pptx", ".ppt")
DEFAULT_PATTERNS = ("*.pptx", "*.ppt", "*.pdf")
INDEX_CACHE_TTL_SEC = 86_400
# Used when collinfo.json is rate-limited (503)
FALLBACK_INDEXES = [
    "CC-MAIN-2025-08",
    "CC-MAIN-2025-05",
    "CC-MAIN-2024-51",
    "CC-MAIN-2024-46",
    "CC-MAIN-2024-42",
]


def _extension_from_url(url: str) -> str:
    from pathlib import Path
    from urllib.parse import urlparse

    return Path(urlparse(url).path).suffix.lower().lstrip(".")


def _read_index_cache(cache_path: Path | None) -> list[str] | None:
    if cache_path is None or not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("ts", 0)) < INDEX_CACHE_TTL_SEC:
            indexes = payload.get("indexes")
            if isinstance(indexes, list) and indexes:
                return [str(x) for x in indexes]
    except Exception:
        pass
    return None


def _write_index_cache(cache_path: Path | None, indexes: list[str]) -> None:
    if cache_path is None or not indexes:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"ts": time.time(), "indexes": indexes}),
        encoding="utf-8",
    )


def list_crawl_indexes(
    client: httpx.Client,
    *,
    cache_path: Path | None = None,
    max_attempts: int = 5,
) -> list[str]:
    """Return crawl index IDs; cache locally and fall back on 503/rate limits."""
    cached = _read_index_cache(cache_path)
    if cached:
        return cached

    for attempt in range(max_attempts):
        try:
            resp = client.get(COLLINFO_URL)
            if resp.status_code in {429, 503, 502}:
                delay = min(60, (2**attempt) + random.uniform(0, 2))
                logger.warning(
                    "Common Crawl collinfo %s — retry in %.1fs (attempt %d/%d)",
                    resp.status_code,
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            indexes = [row["id"] for row in resp.json()]
            if indexes:
                _write_index_cache(cache_path, indexes)
                return indexes
        except httpx.HTTPError as e:
            delay = min(60, (2**attempt) + random.uniform(0, 2))
            logger.warning(
                "Common Crawl collinfo error: %s — retry in %.1fs",
                e,
                delay,
            )
            time.sleep(delay)

    logger.warning("Common Crawl collinfo unavailable — using fallback indexes")
    return list(FALLBACK_INDEXES)


def _worker_page(base_page: int, worker_id: int, worker_count: int) -> int:
    if worker_count <= 1:
        return base_page
    return base_page * worker_count + worker_id


def _fetch_cdx_page(
    client: httpx.Client,
    *,
    active_crawl: str,
    pattern: str,
    cdx_page: int,
    limit: int,
    max_attempts: int = 5,
) -> str | None:
    url = f"https://index.commoncrawl.org/{active_crawl}-index"
    params = {
        "url": pattern,
        "output": "json",
        "limit": limit,
        "page": cdx_page,
        "filter": "status:200",
    }
    for attempt in range(max_attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code in {429, 503, 502}:
                delay = min(90, (2**attempt) * 3 + random.uniform(0, 3))
                logger.warning(
                    "Common Crawl CDX %s for %s page=%s — retry in %.1fs",
                    resp.status_code,
                    pattern,
                    cdx_page,
                    delay,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as e:
            delay = min(90, (2**attempt) * 3 + random.uniform(0, 3))
            logger.warning(
                "Common Crawl CDX failed %s page=%s: %s — retry in %.1fs",
                pattern,
                cdx_page,
                e,
                delay,
            )
            time.sleep(delay)
    return None


def discover_common_crawl(
    *,
    patterns: list[str] | None = None,
    crawl_id: str | None = None,
    page: int = 0,
    limit: int = 5000,
    worker_id: int = 0,
    worker_count: int = 1,
    client: httpx.Client | None = None,
    cache_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Query Common Crawl CDX for presentation URLs.

    Returns (rows, state_patch) where state_patch updates crawl cursor.
    Never raises — returns empty list on persistent API errors.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT})

    patterns = patterns or list(DEFAULT_PATTERNS)
    # Smaller pages reduce 503s when multiple workers query in parallel
    per_pattern_limit = max(200, min(limit, 5000) // max(1, len(patterns)))
    if worker_count > 1:
        per_pattern_limit = max(200, per_pattern_limit // worker_count)

    discovered: list[dict[str, Any]] = []
    state: dict[str, Any] = {
        "page": page,
        "crawl_id": crawl_id,
        "pattern_index": 0,
    }

    try:
        indexes = list_crawl_indexes(client, cache_path=cache_path)
        if not indexes:
            logger.warning("Common Crawl: no indexes available")
            return [], state

        active_crawl = crawl_id if crawl_id in indexes else indexes[0]
        state["crawl_id"] = active_crawl
        cdx_page = _worker_page(page, worker_id, worker_count)

        for pattern in patterns:
            if len(discovered) >= limit:
                break
            body = _fetch_cdx_page(
                client,
                active_crawl=active_crawl,
                pattern=pattern,
                cdx_page=cdx_page,
                limit=per_pattern_limit,
            )
            if not body:
                continue

            for line in body.splitlines():
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
    except Exception as e:
        logger.warning("Common Crawl discovery error: %s", e)
        return [], state
    finally:
        if owns_client and client is not None:
            client.close()
