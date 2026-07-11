"""
tests/test_adapter.py
------------------------
adapter.py (canonical Listing -> analyzer.EtsyAnalyzer 変換層) のテスト。

ここでの目的は「canonical schemaのフィールド名・型が、
analyzer.normalize_listing()が期待する入力と本当に噛み合っているか」を
継続的に検証すること(実装時に手動で突き合わせた結果をコードで固定する)。
analyzer.pyはこのテストでも一切変更しない。
"""

from __future__ import annotations

from adapter import build_analyzer, listing_to_raw_dict, listings_to_raw_dicts
from analyzer import normalize_listing
from interfaces.schema import CANONICAL_FIELDS, empty_listing


def _full_listing():
    """全フィールドに区別可能な値を入れたcanonical Listingを作る。"""
    listing = empty_listing(raw={"source": "test"})
    listing.update(
        {
            "listing_id": 42,
            "title": "Adapter Test Listing",
            "url": "https://example.com/listing/42",
            "price": {"amount": 1234, "divisor": 100, "currency_code": "USD"},
            "quantity": 7,
            "tags": ["alpha", "beta"],
            "materials": ["wood", "glue"],
            "shop_id": 900,
            "shop_name": "AdapterShop",
            "shop_url": "https://example.com/shop/AdapterShop",
            "num_favorers": 55,
            "featured_rank": 2,
            "when_made": "2020_2026",
            "who_made": "i_did",
            "is_customizable": True,
            "taxonomy_id": 77,
            "creation_timestamp": 1710000000,
            "last_modified_timestamp": 1720000000,
            "description": "A listing used to verify the adapter mapping.",
            "images": [
                {
                    "rank": 0,
                    "url_fullxfull": "https://example.com/img/42_full.jpg",
                    "hex_code": "#123456",
                    "brightness": 150,
                }
            ],
        }
    )
    return listing


def test_field_names_are_covered_one_to_one_with_canonical_fields():
    """adapterのフィールド対応表がcanonical schema(raw以外)を過不足なくカバーする。"""
    from adapter import _FIELD_MAPPING

    expected = set(CANONICAL_FIELDS) - {"raw"}
    assert set(_FIELD_MAPPING.keys()) == expected
    assert set(_FIELD_MAPPING.values()) == expected  # 現時点では全て同名対応


def test_listing_to_raw_dict_drops_raw_key():
    raw_dict = listing_to_raw_dict(_full_listing())
    assert "raw" not in raw_dict


def test_listing_to_raw_dict_feeds_normalize_listing_correctly():
    """canonical Listing -> adapter -> analyzer.normalize_listing が期待通り動くことを確認する。"""
    listing = _full_listing()
    raw_dict = listing_to_raw_dict(listing)
    normalized = normalize_listing(raw_dict)

    assert normalized["listing_id"] == 42
    assert normalized["title"] == "Adapter Test Listing"
    assert normalized["url"] == "https://example.com/listing/42"
    assert normalized["price"] == 12.34  # amount(1234) / divisor(100)
    assert normalized["currency_code"] == "USD"
    assert normalized["quantity"] == 7
    assert normalized["tags"] == "alpha; beta"
    assert normalized["tag_count"] == 2
    assert normalized["materials"] == "wood; glue"
    assert normalized["shop_id"] == 900
    assert normalized["shop_name"] == "AdapterShop"
    assert normalized["shop_url"] == "https://example.com/shop/AdapterShop"
    assert normalized["num_favorers"] == 55
    assert normalized["featured_rank"] == 2
    assert normalized["when_made"] == "2020_2026"
    assert normalized["who_made"] == "i_did"
    assert normalized["is_customizable"] is True
    assert normalized["taxonomy_id"] == 77
    assert normalized["creation_timestamp"] == 1710000000
    assert normalized["last_modified_timestamp"] == 1720000000
    assert normalized["description"] == "A listing used to verify the adapter mapping."
    assert normalized["primary_image_url"] == "https://example.com/img/42_full.jpg"
    assert normalized["image_count"] == 1
    assert normalized["image_color_hex"] == "#123456"
    assert normalized["image_brightness"] == 150


def test_listing_to_raw_dict_handles_minimal_listing_without_errors():
    """必須フィールドだけのlistingでもnormalize_listingが例外を出さないこと。"""
    listing = empty_listing(raw={})
    listing["listing_id"] = 1

    raw_dict = listing_to_raw_dict(listing)
    normalized = normalize_listing(raw_dict)

    assert normalized["listing_id"] == 1
    assert normalized["title"] is None
    assert normalized["tags"] == ""
    assert normalized["tag_count"] == 0
    assert normalized["primary_image_url"] is None
    assert normalized["image_count"] == 0


def test_listings_to_raw_dicts_preserves_order_and_count():
    listings = [_full_listing(), empty_listing(raw={})]
    listings[1]["listing_id"] = 2

    raw_dicts = listings_to_raw_dicts(listings)

    assert len(raw_dicts) == 2
    assert raw_dicts[0]["listing_id"] == 42
    assert raw_dicts[1]["listing_id"] == 2


def test_build_analyzer_produces_expected_dataframe():
    listings = [_full_listing()]

    analyzer = build_analyzer(listings, keyword="adapter test")

    assert len(analyzer.df) == 1
    row = analyzer.df.iloc[0]
    assert row["listing_id"] == 42
    assert row["title"] == "Adapter Test Listing"
    assert "score" in analyzer.df.columns
    assert 0 <= row["score"] <= 100


def test_build_analyzer_with_minimal_listing_does_not_raise():
    listing = empty_listing(raw={})
    listing["listing_id"] = 99

    analyzer = build_analyzer([listing], keyword=None)

    assert len(analyzer.df) == 1
    assert analyzer.df.iloc[0]["listing_id"] == 99
