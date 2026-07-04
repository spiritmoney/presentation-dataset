"""robots.txt compliance for downloads."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


@lru_cache(maxsize=256)
def _parser_for_host(scheme: str, netloc: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url(f"{scheme}://{netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        pass
    return rp


def is_allowed(url: str, user_agent: str = USER_AGENT) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return True
    rp = _parser_for_host(parsed.scheme, parsed.netloc)
    return rp.can_fetch(user_agent, url)
