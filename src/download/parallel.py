"""Parallel HTTP downloads — remote http(s) only, never local files."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.download.robots import is_allowed
from src.metadata.schema import RejectionReason
from src.validation.source_url import is_web_source_url, queue_row_is_web

logger = logging.getLogger(__name__)

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def _download_one(
    item: tuple[int, dict, Path, str, bool],
) -> tuple[int, Path | None, dict, str | None]:
    i, row, batch_dir, user_agent, check_robots = item
    url = row.get("url", "")
    meta_base = {
        "source_url": url,
        "category": row.get("category", ""),
        "source_query": row.get("source_query", ""),
    }

    try:
        if not queue_row_is_web(row):
            return i, None, meta_base, "local files are not accepted"

        if check_robots and not is_allowed(url, user_agent):
            return i, None, meta_base, RejectionReason.ROBOTS_DISALLOWED.value

        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext not in PRESENTATION_EXTENSIONS:
            ext = ".pdf"
        dest = batch_dir / f"download_{i:05d}{ext}"

        with httpx.Client(
            timeout=45,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "").lower()
            final_url = str(resp.url)
            if not is_web_source_url(final_url):
                return i, None, meta_base, "download resolved to non-web URL"
            if ext == ".pdf" and "presentation" in ct:
                ext = ".pptx"
                dest = batch_dir / f"download_{i:05d}{ext}"
            dest.write_bytes(resp.content)
            meta = {
                **meta_base,
                "download_url": final_url,
                "original_filename": Path(parsed.path).name or dest.name,
                "http_status": resp.status_code,
                "content_type": ct,
            }
            return i, dest, meta, None
    except Exception as e:
        logger.debug("Download failed %s: %s", url, e)
        return i, None, meta_base, str(e)


def download_batch_parallel(
    rows: list[dict],
    batch_dir: Path,
    *,
    max_workers: int = 64,
    check_robots: bool = True,
    user_agent: str = USER_AGENT,
) -> list[tuple[Path, dict]]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    tasks = [(i, row, batch_dir, user_agent, check_robots) for i, row in enumerate(rows)]
    ok: list[tuple[Path, dict]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_download_one, t) for t in tasks]
        for fut in as_completed(futures):
            _i, dest, meta, err = fut.result()
            if dest is not None:
                ok.append((dest, meta))
    return ok
