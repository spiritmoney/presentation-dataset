"""Tests for blocklist filter."""

from pathlib import Path

from src.filtering.blocklist_filter import BlocklistFilter


def test_blocklist_blocks_f500():
    config_dir = Path(__file__).parent.parent / "config" / "blocklists"
    filt = BlocklistFilter([config_dir / "fortune500.yaml"])
    blocked, reason = filt.check(
        source_url="https://investor.apple.com/deck.pptx",
        organization="Apple Inc.",
    )
    assert blocked is True
    assert reason == "BLOCKLIST_F500"


def test_blocklist_allows_clean_source():
    config_dir = Path(__file__).parent.parent / "config" / "blocklists"
    filt = BlocklistFilter([config_dir / "fortune500.yaml"])
    blocked, reason = filt.check(
        source_url="https://example-startup.com/pitch.pptx",
        organization="Acme Startup",
    )
    assert blocked is False
    assert reason is None


def test_blocklist_blocks_union_pacific_domain():
    config_dir = Path(__file__).parent.parent / "config" / "blocklists"
    filt = BlocklistFilter([config_dir / "fortune500.yaml"])
    blocked, reason = filt.check(
        source_url="https://www.up.com/investor-deck.pptx",
        organization="Union Pacific",
    )
    assert blocked is True
    assert reason == "BLOCKLIST_F500"
