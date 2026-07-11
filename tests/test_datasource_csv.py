"""
tests/test_datasource_csv.py
-------------------------------
interfaces.datasource.CSVDataSource のユニットテスト。

CSV自体は手書きだとJSONのクォート等でミスをしやすいため、
テスト内でcsvモジュールを使って生成する。
"""

from __future__ import annotations

import csv
import json

import pytest

from interfaces.datasource import CSVDataSource, DataSourceError
from interfaces.schema import CANONICAL_FIELDS, validate_listing

CANONICAL_COLUMNS = [name for name in CANONICAL_FIELDS if name != "raw"]


def _write_canonical_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for row in rows:
            encoded = {}
            for col in CANONICAL_COLUMNS:
                value = row.get(col)
                spec = CANONICAL_FIELDS[col]
                if value is None:
                    encoded[col] = ""
                elif spec.is_list or spec.types == (dict,):
                    encoded[col] = json.dumps(value)
                else:
                    encoded[col] = str(value)
            writer.writerow(encoded)


def test_canonical_mode_full_row_is_valid(tmp_path):
    csv_path = tmp_path / "canonical_listings.csv"
    _write_canonical_csv(
        csv_path,
        [
            {
                "listing_id": 111111,
                "title": "Japanese Wall Art Print",
                "url": "https://www.etsy.com/listing/111111/japanese-wall-art-print",
                "price": {"amount": 2500, "divisor": 100, "currency_code": "USD"},
                "quantity": 10,
                "tags": ["japanese wall art", "wabi sabi", "minimalist"],
                "materials": ["paper", "ink"],
                "shop_id": 5551,
                "shop_name": "WashiStudio",
                "shop_url": "https://www.etsy.com/shop/WashiStudio",
                "num_favorers": 342,
                "featured_rank": 3,
                "when_made": "2020_2026",
                "who_made": "i_did",
                "is_customizable": True,
                "taxonomy_id": 1234,
                "creation_timestamp": 1700000000,
                "last_modified_timestamp": 1750000000,
                "description": "A minimalist Japanese-style wall art print.",
                "images": [
                    {
                        "rank": 0,
                        "url_fullxfull": "https://example.com/img1.jpg",
                        "hex_code": "#ffffff",
                        "brightness": 200,
                    }
                ],
            }
        ],
    )

    listings = CSVDataSource(str(csv_path)).fetch_listings(keyword="japanese wall art")

    assert len(listings) == 1
    listing = listings[0]
    assert validate_listing(listing) == []
    assert listing["listing_id"] == 111111
    assert listing["title"] == "Japanese Wall Art Print"
    assert listing["tags"] == ["japanese wall art", "wabi sabi", "minimalist"]
    assert listing["price"] == {"amount": 2500, "divisor": 100, "currency_code": "USD"}
    assert listing["is_customizable"] is True
    assert listing["raw"]["title"] == "Japanese Wall Art Print"  # 元の行がrawに残る


def test_canonical_mode_missing_cells_become_none_and_empty_list(tmp_path):
    csv_path = tmp_path / "sparse_listings.csv"
    _write_canonical_csv(csv_path, [{"listing_id": 222222, "title": "No extra data"}])

    listings = CSVDataSource(str(csv_path)).fetch_listings()

    assert len(listings) == 1
    listing = listings[0]
    assert validate_listing(listing) == []
    assert listing["listing_id"] == 222222
    assert listing["shop_name"] is None
    assert listing["tags"] == []
    assert listing["images"] == []


def test_mapped_mode_arbitrary_column_names(tmp_path):
    csv_path = tmp_path / "mapped_listings.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Name", "Link", "PriceJPY", "TagList"])
        writer.writerow(
            [
                "999888",
                "Sumi-e Style Wall Art",
                "https://www.etsy.com/listing/999888/sumi-e-style-wall-art",
                "",  # priceは今回マッピングしない例
                json.dumps(["sumi-e", "wall art"]),
            ]
        )

    mapping = {
        "listing_id": "ID",
        "title": "Name",
        "url": "Link",
        "tags": "TagList",
    }
    listings = CSVDataSource(str(csv_path), column_mapping=mapping).fetch_listings()

    assert len(listings) == 1
    listing = listings[0]
    assert validate_listing(listing) == []
    assert listing["listing_id"] == 999888
    assert listing["title"] == "Sumi-e Style Wall Art"
    assert listing["tags"] == ["sumi-e", "wall art"]
    # マッピングされなかったcanonical fieldは欠損値ルール通りNone/[]
    assert listing["price"] is None
    assert listing["materials"] == []


def test_max_results_truncates(tmp_path):
    csv_path = tmp_path / "many_listings.csv"
    _write_canonical_csv(
        csv_path,
        [{"listing_id": i, "title": f"Item {i}"} for i in range(5)],
    )

    listings = CSVDataSource(str(csv_path)).fetch_listings(max_results=2)
    assert len(listings) == 2


def test_missing_file_raises_datasource_error(tmp_path):
    missing_path = tmp_path / "does_not_exist.csv"
    with pytest.raises(DataSourceError):
        CSVDataSource(str(missing_path)).fetch_listings()
