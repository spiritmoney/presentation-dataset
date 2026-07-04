"""Tests for Common Crawl and URL catalog filtering."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.crawlers.common_crawl import FALLBACK_INDEXES, discover_common_crawl, list_crawl_indexes
from src.crawlers.url_filter import filter_catalog_rows, is_catalog_candidate


def test_is_catalog_candidate_rejects_non_web():
    assert is_catalog_candidate("file:///tmp/x.pdf") is False
    assert is_catalog_candidate("https://example.com/report.pdf") is True
    assert is_catalog_candidate("https://example.com/page.html") is False


def test_filter_catalog_rows():
    rows = [
        {"url": "https://a.com/deck.pptx"},
        {"url": "https://b.com/page.html"},
    ]
    out = filter_catalog_rows(rows, apply_denylist=False)
    assert len(out) == 1
    assert out[0]["url"].endswith(".pptx")


def test_list_crawl_indexes_falls_back_on_503():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 503
    client.get.return_value = resp

    indexes = list_crawl_indexes(client, max_attempts=2)
    assert indexes == FALLBACK_INDEXES


@patch("src.crawlers.common_crawl.list_crawl_indexes")
def test_discover_common_crawl_parses_ndjson(mock_indexes):
    mock_indexes.return_value = ["CC-MAIN-TEST"]
    line = json.dumps(
        {
            "url": "https://cdn.example.com/deck.pptx",
            "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "status": "200",
            "timestamp": "20240101",
        }
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = line + "\n"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    hits, state = discover_common_crawl(
        patterns=["*.pptx"],
        crawl_id="CC-MAIN-TEST",
        page=0,
        limit=100,
        client=mock_client,
    )
    assert len(hits) == 1
    assert hits[0]["source"] == "common_crawl"
    assert state["page"] == 1
