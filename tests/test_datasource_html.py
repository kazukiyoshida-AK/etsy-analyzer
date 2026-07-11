"""
tests/test_datasource_html.py
--------------------------------
interfaces.datasource.HTMLDataSource と
interfaces.html_parsers.EtsyHTMLParser のユニットテスト。

対象はすべて保存済みHTML(ファイル/文字列)であり、
ネットワークアクセスは一切発生しない。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from interfaces.datasource import DataSourceError, HTMLDataSource
from interfaces.html_parsers import EtsyHTMLParser, HTMLListingParser
from interfaces.schema import validate_listing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_etsy_html_parser_extracts_product_from_json_ld():
    html = (FIXTURES_DIR / "etsy_listing.html").read_text(encoding="utf-8")
    items = EtsyHTMLParser().parse(html)

    assert len(items) == 1
    item = items[0]
    assert item["listing_id"] == 333444555
    assert item["title"] == "Japanese Wall Art Hanging Scroll"
    assert item["shop_name"] == "KyotoScrollWorks"
    assert item["price"] == {"amount": 4500, "divisor": 100, "currency_code": "USD"}
    assert item["images"] == [
        {"rank": 0, "url_fullxfull": "https://example.com/img/333444555_1.jpg"},
        {"rank": 1, "url_fullxfull": "https://example.com/img/333444555_2.jpg"},
    ]
    assert item["raw"]["name"] == "Japanese Wall Art Hanging Scroll"


def test_etsy_html_parser_returns_empty_list_when_no_json_ld():
    items = EtsyHTMLParser().parse("<html><body>no structured data here</body></html>")
    assert items == []


def test_etsy_html_parser_skips_product_without_extractable_listing_id():
    html = """
    <script type="application/ld+json">
    {"@type": "Product", "name": "No URL Product"}
    </script>
    """
    items = EtsyHTMLParser().parse(html)
    assert items == []


def test_html_datasource_reads_file_and_validates():
    listings = HTMLDataSource(str(FIXTURES_DIR / "etsy_listing.html")).fetch_listings()

    assert len(listings) == 1
    listing = listings[0]
    assert validate_listing(listing) == []
    assert listing["listing_id"] == 333444555
    assert listing["tags"] == []  # パーサーが返さなかったフィールドは空リストで埋まる
    assert listing["materials"] == []


def test_html_datasource_accepts_multiple_paths_and_respects_max_results(tmp_path):
    class TwoItemParser(HTMLListingParser):
        def parse(self, html: str) -> List[Dict[str, Any]]:
            return [
                {"listing_id": 1, "title": "A", "raw": {"src": html[:5]}},
                {"listing_id": 2, "title": "B", "raw": {"src": html[:5]}},
            ]

    path_a = tmp_path / "a.html"
    path_b = tmp_path / "b.html"
    path_a.write_text("AAAAA", encoding="utf-8")
    path_b.write_text("BBBBB", encoding="utf-8")

    listings = HTMLDataSource(
        [str(path_a), str(path_b)], parser=TwoItemParser()
    ).fetch_listings(max_results=3)

    assert len(listings) == 3
    for listing in listings:
        assert validate_listing(listing) == []


def test_html_datasource_missing_file_raises_datasource_error(tmp_path):
    missing_path = tmp_path / "does_not_exist.html"
    with pytest.raises(DataSourceError):
        HTMLDataSource(str(missing_path)).fetch_listings()


def test_html_datasource_wraps_parser_exceptions(tmp_path):
    class BrokenParser(HTMLListingParser):
        def parse(self, html: str) -> List[Dict[str, Any]]:
            raise ValueError("boom")

    path = tmp_path / "x.html"
    path.write_text("<html></html>", encoding="utf-8")

    with pytest.raises(DataSourceError):
        HTMLDataSource(str(path), parser=BrokenParser()).fetch_listings()
