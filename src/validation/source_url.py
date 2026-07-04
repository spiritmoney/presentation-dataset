"""Verify source URL reachability and public accessibility."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from src.metadata.schema import SourceStatus

USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def is_web_source_url(url: str | None) -> bool:
    """True only for public http(s) URLs — not file://, seeds, or synthetic."""
    if not url or not isinstance(url, str):
        return False
    scheme = urlparse(url.strip()).scheme.lower()
    return scheme in ("http", "https")


def is_local_source(
    *,
    source_url: str | None = None,
    download_url: str | None = None,
    local_path: str | None = None,
    content_type: str | None = None,
    public_access_status: str | None = None,
    category: str | None = None,
    source_query: str | None = None,
) -> tuple[bool, str]:
    """
    Detect local / non-web sources that must never enter qualified/.

    Returns (is_local, reason).
    """
    if local_path:
        return True, "local_path is set"
    if category and str(category).lower() in {"seed", "local", "fixture"}:
        return True, f"local category={category}"
    if source_query and str(source_query).lower() in {"local_seed", "seed", "fixture"}:
        return True, f"local source_query={source_query}"
    if content_type and "local" in str(content_type).lower():
        return True, f"local content_type={content_type}"
    if public_access_status and str(public_access_status).upper() == "LOCAL":
        return True, "public_access_status=LOCAL"
    if not is_web_source_url(source_url):
        return True, f"non-web source_url={source_url or 'missing'}"
    if download_url and not is_web_source_url(download_url):
        return True, f"non-web download_url={download_url}"
    return False, ""


def queue_row_is_web(row: dict) -> bool:
    """True if a discovery/download queue row is a remote http(s) URL only."""
    if row.get("local_path"):
        return False
    if not is_web_source_url(row.get("url")):
        return False
    local, _ = is_local_source(
        source_url=row.get("url"),
        category=row.get("category"),
        source_query=row.get("source_query"),
    )
    return not local


@dataclass
class SourceUrlCheck:
    source_status: SourceStatus
    public_access: str  # PASS | FAIL | LOCAL | UNKNOWN
    http_status: int | None = None
    final_url: str | None = None
    error: str | None = None


def verify_source_url(
    url: str,
    *,
    timeout_sec: float = 15,
    client: httpx.Client | None = None,
) -> SourceUrlCheck:
    """Check whether a source URL is reachable and publicly accessible."""
    if not is_web_source_url(url):
        parsed = urlparse(url or "")
        if parsed.scheme == "file":
            return SourceUrlCheck(
                source_status=SourceStatus.UNREACHABLE,
                public_access="FAIL",
                final_url=url,
                error="file:// sources are not web sources",
            )
        return SourceUrlCheck(
            source_status=SourceStatus.UNKNOWN,
            public_access="FAIL",
            error=f"unsupported scheme: {parsed.scheme or 'missing'}",
        )

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return SourceUrlCheck(
            source_status=SourceStatus.UNKNOWN,
            public_access="UNKNOWN",
            error=f"unsupported scheme: {parsed.scheme}",
        )

    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=timeout_sec,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    try:
        resp = client.head(url)
        if resp.status_code >= 400:
            resp = client.get(url)
        status = resp.status_code
        final = str(resp.url)

        if 200 <= status < 400:
            return SourceUrlCheck(
                source_status=SourceStatus.REACHABLE,
                public_access="PASS",
                http_status=status,
                final_url=final,
            )
        if status in (401, 403):
            return SourceUrlCheck(
                source_status=SourceStatus.UNREACHABLE,
                public_access="FAIL",
                http_status=status,
                final_url=final,
                error="access denied",
            )
        return SourceUrlCheck(
            source_status=SourceStatus.UNREACHABLE,
            public_access="FAIL",
            http_status=status,
            final_url=final,
            error=f"http {status}",
        )
    except Exception as e:
        return SourceUrlCheck(
            source_status=SourceStatus.UNREACHABLE,
            public_access="FAIL",
            error=str(e),
        )
    finally:
        if owns_client:
            client.close()
