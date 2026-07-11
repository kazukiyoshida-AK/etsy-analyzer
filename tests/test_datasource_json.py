"""
tests/test_datasource_json.py
--------------------------------
interfaces.datasource.JSONDataSource のユニットテスト。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interfaces.datasource import DataSourceError, JSONDataSource
from interfaces.schema import validate_listing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_results_key_unwraps_and_validates():
    listings = JSONDataSource(
        str(FIXTURES_DIR / "listings.json"), results_key="results"
    ).fetch_listings()

    assert len(listings) == 2
    for listing in listings:
        assert validate_listing(listing) == []

    full, partial = listings
    assert full["listing_id"] == 222222
    assert full["tags"] == ["japanese wall art", "sumi-e", "zen"]
    assert full["price"] == {"amount": 3200, "divisor": 100, "currency_code": "USD"}
    assert full["raw"]["shop_name"] == "ZenPrintStudio"


def test_partial_item_gets_none_and_empty_list_defaults():
    listings = JSONDataSource(
        str(FIXTURES_DIR / "listings.json"), results_key="results"
    ).fetch_listings()

    partial = listings[1]
    assert partial["listing_id"] == 222333
    assert partial["title"] == "Japanese Cherry Blossom Canvas Print"
    assert partial["shop_name"] is None
    assert partial["tags"] == []
    assert partial["images"] == []


def test_plain_list_json_without_results_key(tmp_path):
    path = tmp_path / "plain_list.json"
    path.write_text(
        json.dumps([{"listing_id": 1, "title": "A"}, {"listing_id": 2, "title": "B"}]),
        encoding="utf-8",
    )

    listings = JSONDataSource(str(path)).fetch_listings()
    assert [l["listing_id"] for l in listings] == [1, 2]
    for listing in listings:
        assert validate_listing(listing) == []


def test_max_results_truncates(tmp_path):
    path = tmp_path / "many.json"
    path.write_text(
        json.dumps([{"listing_id": i} for i in range(10)]), encoding="utf-8"
    )

    listings = JSONDataSource(str(path)).fetch_listings(max_results=3)
    assert len(listings) == 3


def test_non_list_top_level_raises(tmp_path):
    path = tmp_path / "not_a_list.json"
    path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    with pytest.raises(DataSourceError):
        JSONDataSource(str(path)).fetch_listings()


def test_results_key_missing_defaults_to_empty_list(tmp_path):
    path = tmp_path / "no_results_key.json"
    path.write_text(json.dumps({"other": []}), encoding="utf-8")

    listings = JSONDataSource(str(path), results_key="results").fetch_listings()
    assert listings == []


def test_invalid_json_raises_datasource_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(DataSourceError):
        JSONDataSource(str(path)).fetch_listings()


def test_missing_file_raises_datasource_error(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    with pytest.raises(DataSourceError):
        JSONDataSource(str(missing_path)).fetch_listings()
