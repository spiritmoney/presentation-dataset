"""Blocklist matching against F500, universities, and think tanks."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml


def _normalize_host(host: str) -> str:
    host = host.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _domain_matches(netloc: str, blocked_domain: str) -> bool:
    """True if netloc is exactly blocked_domain or a subdomain of it."""
    host = _normalize_host(netloc)
    blocked = _normalize_host(blocked_domain)
    if not host or not blocked:
        return False
    return host == blocked or host.endswith(f".{blocked}")


def _name_matches(text: str, name: str) -> bool:
    """Word-boundary aware name match to reduce false positives."""
    if not name or len(name) < 3:
        return False
    pattern = rf"\b{re.escape(name.lower())}\b"
    return re.search(pattern, text.lower()) is not None


class BlocklistFilter:
    def __init__(self, blocklist_paths: list[Path]):
        self.entries: list[dict] = []
        for path in blocklist_paths:
            if path.exists():
                with path.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                self.entries.append(data)

    def _match_org(
        self,
        *,
        combined_text: str,
        source_netloc: str,
        names: list[str],
        domains: list[str],
    ) -> bool:
        for name in names:
            if _name_matches(combined_text, name):
                return True
        for domain in domains:
            if _domain_matches(source_netloc, domain):
                return True
            # Also check if full blocked domain appears as a host in text (metadata fields)
            if domain and _normalize_host(domain) in _normalize_host(combined_text):
                # Only if it looks like a URL/host reference, not substring noise
                if re.search(rf"\b{re.escape(_normalize_host(domain))}\b", combined_text.lower()):
                    return True
        return False

    def check(
        self,
        source_url: str,
        organization: str = "",
        title: str = "",
        filename: str = "",
    ) -> tuple[bool, str | None]:
        """Return (is_blocked, reason_code)."""
        parsed = urlparse(source_url)
        source_netloc = parsed.netloc or ""
        combined = f"{source_url} {organization} {title} {filename}"

        for entry in self.entries:
            orgs = entry.get("companies") or entry.get("institutions") or entry.get("organizations") or []
            for org in orgs:
                names = [org.get("name", "")] + org.get("aliases", [])
                domains = org.get("domains", [])
                if self._match_org(
                    combined_text=combined,
                    source_netloc=source_netloc,
                    names=names,
                    domains=domains,
                ):
                    if "companies" in entry:
                        return True, "BLOCKLIST_F500"
                    if "institutions" in entry:
                        return True, "BLOCKLIST_UNIVERSITY"
                    if "organizations" in entry:
                        return True, "BLOCKLIST_THINKTANK"

        return False, None
