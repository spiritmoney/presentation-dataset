"""Continuous URL collection — Common Crawl + web search → PostgreSQL catalog."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from src.config import Settings, get_config_dir, get_target_count, load_yaml_config
from src.crawlers.common_crawl import discover_common_crawl
from src.crawlers.url_filter import filter_catalog_rows
from src.crawlers.web_search import discover_web_search
from src.crawlers.archive_org import discover_archive_org
from src.pipeline.discovery import _discovery_flags
from src.storage.backend import get_store, use_postgres
from src.supervisor.state import RunStatus, StateManager

import httpx

logger = logging.getLogger(__name__)
USER_AGENT = "PresentationDatasetBot/0.1 (+research)"


def _worker_id() -> int:
    return int(os.environ.get("WORKER_ID", "0"))


def _worker_count() -> int:
    return max(1, int(os.environ.get("WORKER_COUNT", "1")))


def _state_path(data_dir: Path) -> Path:
    return data_dir / "state" / f"collect_worker_{_worker_id()}.json"


def _load_state(data_dir: Path) -> dict:
    path = _state_path(data_dir)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"common_crawl_page": 0, "crawl_id": None, "web_search_offset": 0, "archive_page": 1}


def _save_state(data_dir: Path, state: dict) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _collect_once(data_dir: Path, perf: dict) -> int:
    """Run one discovery cycle; return URLs newly inserted into catalog."""
    if not use_postgres():
        raise RuntimeError("URL catalog collection requires PostgreSQL (DATABASE_URL)")

    store = get_store()
    flags = _discovery_flags()
    sources = load_yaml_config(get_config_dir() / "sources.yaml")
    state = _load_state(data_dir)
    worker_id = _worker_id()
    worker_count = _worker_count()
    discovered: list[dict] = []

    cc_limit = int(perf.get("common_crawl_limit", flags.get("common_crawl_limit", 10000)))
    patterns = sources.get("common_crawl_patterns") or [
        "*.pptx",
        "*.ppt",
        "*.pdf",
    ]

    if flags.get("enable_common_crawl", True):
        hits, cc_state = discover_common_crawl(
            patterns=patterns,
            crawl_id=state.get("crawl_id"),
            page=int(state.get("common_crawl_page", 0)),
            limit=cc_limit,
            worker_id=worker_id,
            worker_count=worker_count,
        )
        discovered.extend(hits)
        state["common_crawl_page"] = cc_state.get("page", state.get("common_crawl_page", 0))
        state["crawl_id"] = cc_state.get("crawl_id", state.get("crawl_id"))
        if hits:
            logger.info("Common Crawl worker=%s: %d raw URLs", worker_id, len(hits))

    if flags["enable_web_search"]:
        search_queries = sources.get("search_queries", [])
        if search_queries:
            offset = int(state.get("web_search_offset", 0))
            hits = discover_web_search(
                search_queries,
                results_per_query=int(perf.get("web_search_results_per_query", 40)),
                max_total=int(perf.get("web_search_max_per_discover", 500)),
                query_offset=offset,
                follow_landing_pages=int(flags.get("web_search_follow_landing_pages", 10)),
            )
            for row in hits:
                row["source"] = "web_search"
            discovered.extend(hits)
            state["web_search_offset"] = offset + max(1, len(search_queries) // 4)

    if flags["enable_archive_org"]:
        archive_queries = sources.get("archive_queries", [])
        if archive_queries:
            page = int(state.get("archive_page", 1))
            try:
                with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
                    hits = discover_archive_org(
                        archive_queries,
                        client=client,
                        rows_per_query=int(perf.get("archive_rows_per_query", 100)),
                        max_files_per_item=int(perf.get("archive_files_per_item", 3)),
                        max_total=int(perf.get("archive_max_per_discover", 2000)),
                        page=page,
                    )
                for row in hits:
                    row["source"] = "archive_org"
                    row["file_type"] = (row.get("url") or "").rsplit(".", 1)[-1].lower()
                discovered.extend(hits)
                state["archive_page"] = page + 1
            except Exception as e:
                logger.warning("Archive.org collect failed: %s", e)

    filtered = filter_catalog_rows(discovered)
    inserted = store.insert_url_catalog_batch(filtered, worker_id=worker_id)
    _save_state(data_dir, state)
    logger.info(
        "Collect worker=%s/%s: filtered=%d inserted=%d catalog_total=%d",
        worker_id,
        worker_count,
        len(filtered),
        inserted,
        store.count_url_catalog(),
    )
    return inserted


def run_url_collection(
    *,
    data_dir: Path | None = None,
    target_count: int | None = None,
    pause_sec: float = 2.0,
) -> int:
    """
    Loop until url_catalog reaches target_count.

    Stores links + metadata only — no file downloads.
    """
    settings = Settings()
    base = data_dir or Path(settings.data_dir)
    pipeline = load_yaml_config(get_config_dir() / "pipeline.yaml")
    target = target_count if target_count is not None else get_target_count(pipeline)
    perf = pipeline.get("performance", {}).get("turbo", {})

    store = get_store()
    state_path = base / "state" / "pipeline_state.json"
    manager = StateManager(state_path)
    state = manager.init_or_resume(target)
    state.status = RunStatus.RUNNING
    state.current_stage = "collect_urls"
    manager.save(state)

    logger.info(
        "URL collection started worker=%s/%s target=%s",
        _worker_id(),
        _worker_count(),
        f"{target:,}",
    )

    while True:
        current = store.count_url_catalog()
        state.accepted_count = current
        state.touch_progress()
        manager.save(state)

        if current >= target:
            state.status = RunStatus.GOAL_REACHED
            manager.save(state)
            logger.info("URL catalog goal reached: %s", f"{current:,}")
            return current

        added = _collect_once(base, perf)
        if added == 0:
            time.sleep(max(pause_sec, 5.0))
        else:
            time.sleep(pause_sec)
