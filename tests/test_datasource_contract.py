"""
tests/test_datasource_contract.py
------------------------------------
DataSourceの共通契約テスト (方針8)。

「取得方法が何であれ、fetch_listings()が返すdictは必ず
canonical schemaを満たす」という契約を、4実装すべてに対して
同じアサーションで検証する。新しいDataSource実装を追加した場合も
CASES に1エントリ追加するだけでこの契約テストの対象にできる。

このファイルは他のtest_datasource_*.pyのフィクスチャに依存せず、
それぞれ最小限のサンプルデータをこの中で組み立てて完結させる。
"""

from __future__ import annotations

import csv
import json
from typing import Any, Dict, List

import pytest

from interfaces.datasource import (
    CSVDataSource,
    DataSource,
    HTMLDataSource,
    JSONDataSource,
)
from interfaces.datasource import EtsyAPIDataSource
from interfaces.html_parsers import HTMLListingParser
from interfaces.schema import CANONICAL_FIELDS, REQUIRED_KEYS, SCHEMA_VERSION, validate_listing


def test_datasource_is_an_abstract_base_class():
    """DataSourceは直接インスタンス化できない(方針1: ABCとして定義)。"""
    with pytest.raises(TypeError):
        DataSource()  # type: ignore[abstract]


# ----------------------------------------------------------------------
# 各実装ごとの最小サンプルセットアップ
# ----------------------------------------------------------------------
def _build_csv_source(tmp_path) -> DataSource:
    path = tmp_path / "contract_canonical.csv"
    columns = [name for name in CANONICAL_FIELDS if name != "raw"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "listing_id": "1",
                "title": "Contract Test Item",
                "tags": json.dumps(["a", "b"]),
                "price": json.dumps({"amount": 1000, "divisor": 100, "currency_code": "USD"}),
            }
        )
    return CSVDataSource(str(path))


def _build_csv_mapped_source(tmp_path) -> DataSource:
    path = tmp_path / "contract_mapped.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ProductID", "ProductName"])
        writer.writerow(["2", "Mapped Contract Test Item"])
    mapping = {"listing_id": "ProductID", "title": "ProductName"}
    return CSVDataSource(str(path), column_mapping=mapping)


def _build_json_source(tmp_path) -> DataSource:
    path = tmp_path / "contract.json"
    path.write_text(
        json.dumps([{"listing_id": 3, "title": "JSON Contract Test Item"}]),
        encoding="utf-8",
    )
    return JSONDataSource(str(path))


def _build_html_source(tmp_path) -> DataSource:
    class FakeParser(HTMLListingParser):
        def parse(self, html: str) -> List[Dict[str, Any]]:
            return [{"listing_id": 4, "title": "HTML Contract Test Item", "raw": {"src": html}}]

    path = tmp_path / "contract.html"
    path.write_text("<html><body>irrelevant</body></html>", encoding="utf-8")
    return HTMLDataSource(str(path), parser=FakeParser())


def _build_etsy_api_source(tmp_path) -> DataSource:
    class FakeClient:
        def search_active_listings(self, keyword, max_results=50, sort_on="score"):
            return [
                {
                    "listing_id": 5,
                    "title": "Etsy API Contract Test Item",
                    "tags": ["a"],
                }
            ]

        def enrich_listings(self, listings):
            return listings

    return EtsyAPIDataSource(client=FakeClient())


CASES = {
    "csv_canonical": _build_csv_source,
    "csv_mapped": _build_csv_mapped_source,
    "json": _build_json_source,
    "html": _build_html_source,
    "etsy_api": _build_etsy_api_source,
}


@pytest.fixture(params=sorted(CASES.keys()))
def datasource_instance(request, tmp_path) -> DataSource:
    build = CASES[request.param]
    return build(tmp_path)


@pytest.fixture
def listings_from_source(datasource_instance) -> List[Dict[str, Any]]:
    return datasource_instance.fetch_listings(keyword="contract test", max_results=10)


# ----------------------------------------------------------------------
# 共通契約テスト本体
# ----------------------------------------------------------------------
def test_source_is_a_datasource_instance(datasource_instance):
    """全実装がDataSource(ABC)のサブクラスであること(方針1)。"""
    assert isinstance(datasource_instance, DataSource)


def test_source_declares_schema_version(datasource_instance):
    """全実装がcanonical schemaのバージョンを持つこと(方針3)。"""
    assert datasource_instance.schema_version == SCHEMA_VERSION


def test_fetch_listings_returns_a_list(datasource_instance):
    """fetch_listings()の戻り値は必ずList[Listing]であること(方針2)。"""
    listings = datasource_instance.fetch_listings(keyword="contract test", max_results=10)
    assert isinstance(listings, list)
    for listing in listings:
        assert isinstance(listing, dict)  # ListingはTypedDict = 実体はdict


def test_source_returns_at_least_one_listing(listings_from_source):
    assert len(listings_from_source) >= 1


def test_every_listing_satisfies_canonical_schema(listings_from_source):
    for listing in listings_from_source:
        errors = validate_listing(listing)
        assert errors == [], f"canonical schema violations: {errors}"


def test_every_listing_has_all_required_keys(listings_from_source):
    for listing in listings_from_source:
        for key in REQUIRED_KEYS:
            assert key in listing, f"missing required key: {key}"
            assert listing[key] is not None


def test_every_listing_has_raw_dict_with_original_data(listings_from_source):
    for listing in listings_from_source:
        assert isinstance(listing["raw"], dict)
        assert len(listing["raw"]) > 0


def test_list_fields_are_always_lists_never_none(listings_from_source):
    list_fields = [name for name, spec in CANONICAL_FIELDS.items() if spec.is_list]
    for listing in listings_from_source:
        for field in list_fields:
            assert isinstance(listing[field], list), f"{field} must be a list, got None/other"


def test_optional_scalar_fields_are_type_or_none(listings_from_source):
    scalar_fields = [
        name
        for name, spec in CANONICAL_FIELDS.items()
        if not spec.is_list and not spec.required
    ]
    for listing in listings_from_source:
        for field in scalar_fields:
            value = listing[field]
            spec = CANONICAL_FIELDS[field]
            assert value is None or isinstance(value, spec.types)


def test_no_keys_outside_canonical_schema(listings_from_source):
    for listing in listings_from_source:
        assert set(listing.keys()) == set(CANONICAL_FIELDS.keys())
