"""Discover presentation URLs via public web search (no API key)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from src.validation.source_url import is_web_source_url

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = (".pdf", ".pptx", ".ppt")
_HREF_PATTERN = re.compile(
    r"""href=["']([^"']+\.(?:pptx?|pdf)(?:\?[^"']*)?)["']""",
    re.IGNORECASE,
)
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def _path_ends_presentation(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in PRESENTATION_EXTENSIONS)


def _normalize_queries(queries: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in queries:
        if isinstance(item, str):
            q = item.strip()
            if q:
                out.append({"query": q, "category": "web"})
        elif isinstance(item, dict):
            q = str(item.get("query", "")).strip()
            if q:
                out.append({"query": q, "category": str(item.get("category", "web"))})
    return out


def extract_presentation_urls_from_html(html: str, base_url: str) -> list[str]:
    """Pull direct .pdf/.ppt/.pptx links from an HTML page."""
    found: list[str] = []
    for match in _HREF_PATTERN.findall(html):
        url = urljoin(base_url, match)
        if _path_ends_presentation(url) and is_web_source_url(url):
            found.append(url)
    return found


def discover_web_search(
    queries: list[Any],
    *,
    results_per_query: int = 30,
    max_total: int = 500,
    query_offset: int = 0,
    follow_landing_pages: int = 10,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """
    Search the web for presentation files using DuckDuckGo.

    Uses queries from config/sources.yaml (filetype:pptx, filetype:pdf, etc.).
    When a result is an HTML page, optionally scans it for embedded file links.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search not installed — pip install duckduckgo-search")
        return []

    normalized = _normalize_queries(queries)
    if not normalized:
        return []

    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    landing_budget = follow_landing_pages

    try:
        with DDGS() as ddgs:
            rounds = max(1, min(len(normalized), max_total // max(1, results_per_query) + 1))
            for i in range(rounds):
                if len(discovered) >= max_total:
                    break
                item = normalized[(query_offset + i) % len(normalized)]
                query = item["query"]
                try:
                    results = ddgs.text(query, max_results=results_per_query)
                except Exception as e:
                    logger.warning("Web search query failed '%s': %s", query, e)
                    continue

                for row in results:
                    if len(discovered) >= max_total:
                        break
                    href = (row.get("href") or row.get("link") or "").strip()
                    if not href or not is_web_source_url(href):
                        continue

                    if _path_ends_presentation(href):
                        if href in seen:
                            continue
                        seen.add(href)
                        discovered.append(
                            {
                                "url": href,
                                "source_query": query,
                                "category": item["category"],
                                "document_title": row.get("title", ""),
                            }
                        )
                        continue

                    # Landing page — look for embedded presentation links
                    if landing_budget <= 0:
                        continue
                    try:
                        resp = client.get(href)
                        if resp.status_code != 200:
                            continue
                        ctype = resp.headers.get("content-type", "").lower()
                        if "html" not in ctype:
                            continue
                        landing_budget -= 1
                        for file_url in extract_presentation_urls_from_html(resp.text, str(resp.url)):
                            if file_url in seen or len(discovered) >= max_total:
                                continue
                            seen.add(file_url)
                            discovered.append(
                                {
                                    "url": file_url,
                                    "source_query": query,
                                    "category": item["category"],
                                    "document_title": row.get("title", ""),
                                    "landing_page": href,
                                }
                            )
                    except Exception:
                        continue
    finally:
        if owns_client and client is not None:
            client.close()

    return discovered
