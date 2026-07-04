"""Discover presentation URLs from Archive.org."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = (".pdf", ".pptx", ".ppt")
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def discover_archive_org(
    queries: list[str],
    *,
    rows_per_query: int = 10,
    max_files_per_item: int = 2,
    max_total: int = 30,
    page: int = 1,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Search Archive.org and return downloadable presentation URLs."""
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=45, headers={"User-Agent": USER_AGENT})

    discovered: list[dict[str, Any]] = []
    try:
        for query in queries:
            if len(discovered) >= max_total:
                break
            try:
                resp = client.get(
                    "https://archive.org/advancedsearch.php",
                    params={
                        "q": query,
                        "fl": "identifier,title",
                        "rows": rows_per_query,
                        "page": page,
                        "output": "json",
                    },
                )
                resp.raise_for_status()
                docs = resp.json().get("response", {}).get("docs", [])
                for doc in docs:
                    ident = doc.get("identifier")
                    if not ident:
                        continue
                    meta_resp = client.get(f"https://archive.org/metadata/{ident}")
                    if meta_resp.status_code != 200:
                        continue
                    files = meta_resp.json().get("files", [])
                    added = 0
                    for file_info in files:
                        if len(discovered) >= max_total:
                            break
                        name = file_info.get("name", "")
                        lower = name.lower()
                        if not lower.endswith(PRESENTATION_EXTENSIONS):
                            continue
                        if file_info.get("private") == "true":
                            continue
                        url = f"https://archive.org/download/{quote(ident)}/{quote(name)}"
                        discovered.append(
                            {
                                "url": url,
                                "source_query": query,
                                "category": "archive_org",
                                "discovered_at": None,
                                "archive_identifier": ident,
                                "document_title": doc.get("title", ""),
                            }
                        )
                        added += 1
                        if added >= max_files_per_item:
                            break
            except Exception as e:
                logger.warning("Archive.org query failed '%s': %s", query, e)
    finally:
        if owns_client:
            client.close()
    return discovered
