"""Tests for autonomous web search discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.crawlers.web_search import (
    discover_web_search,
    extract_presentation_urls_from_html,
)


def test_extract_presentation_urls_from_html():
    html = '''
    <a href="/files/deck.pptx">Deck</a>
    <a href="https://cdn.example.com/report.pdf">PDF</a>
  '''
    urls = extract_presentation_urls_from_html(html, "https://example.com/page")
    assert "https://example.com/files/deck.pptx" in urls
    assert "https://cdn.example.com/report.pdf" in urls


@patch("duckduckgo_search.DDGS")
def test_discover_web_search_direct_file_links(mock_ddgs_cls):
    mock_ddgs = MagicMock()
    mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs
    mock_ddgs.text.return_value = [
        {"href": "https://files.example.com/slides.pptx", "title": "Slides"},
        {"href": "https://example.com/page", "title": "Landing"},
    ]

    hits = discover_web_search(
        [{"query": "filetype:pptx dashboard", "category": "data_viz"}],
        results_per_query=5,
        max_total=10,
        follow_landing_pages=0,
        client=MagicMock(),
    )
    assert len(hits) == 1
    assert hits[0]["url"].endswith(".pptx")
    assert hits[0]["category"] == "data_viz"
