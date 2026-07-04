"""Lightweight URL filtering before catalog ingest (no download)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from src.config import get_config_dir, load_yaml_config
from src.validation.source_url import is_web_source_url

PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pdf"}


def _load_denylist() -> list[str]:
    sources = load_yaml_config(get_config_dir() / "sources.yaml")
    return list(sources.get("denylist", []))


def _domain_denied(host: str, denylist: list[str]) -> bool:
    host = host.lower()
    for pattern in denylist:
        p = pattern.lower().lstrip("*.")
        if pattern.startswith("*.") and (host == p or host.endswith("." + p)):
            return True
        if host == pattern.lower():
            return True
    return False


def is_catalog_candidate(url: str, *, apply_denylist: bool = True) -> bool:
    """True when URL looks like a web presentation link worth cataloging."""
    if not url or not is_web_source_url(url):
        return False
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in PRESENTATION_EXTENSIONS:
        return False
    if apply_denylist and _domain_denied(parsed.netloc, _load_denylist()):
        return False
    return True


def filter_catalog_rows(rows: list[dict], *, apply_denylist: bool = True) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        url = (row.get("url") or "").strip()
        if is_catalog_candidate(url, apply_denylist=apply_denylist):
            out.append(row)
    return out
