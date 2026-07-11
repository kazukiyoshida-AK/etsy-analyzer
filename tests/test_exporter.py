"""
tests/test_exporter.py
-----------------------
exporter.generate_ai_json / save_ai_json のユニットテスト。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from analyzer import EtsyAnalyzer
from exporter import DESCRIPTION_MAX_CHARS, DISCLAIMER, generate_ai_json, save_ai_json


def _make_raw_listing(**overrides):
    now = int(time.time())
    base = {
        "listing_id": 1,
        "title": "Japanese Wall Art Print",
        "url": "https://etsy.com/listing/1",
        "description": "A beautiful minimalist Japanese wall art print. " * 20,
        "price": {"amount": 2500, "divisor": 100, "currency_code": "USD"},
        "quantity": 5,
        "tags": ["japanese", "wall art", "print", "minimalist"],
        "materials": ["paper"],
        "shop_id": 111,
        "shop_name": "ArtShopA",
        "shop_url": "https://etsy.com/shop/ArtShopA",
        "num_favorers": 120,
        "featured_rank": 1,
        "when_made": "2020_2024",
        "who_made": "i_did",
        "is_customizable": False,
        "taxonomy_id": 1,
        "creation_timestamp": now - 100000,
        "last_modified_timestamp": now,
        "images": [
            {"rank": 1, "hex_code": "ffffff", "brightness": 230, "url_fullxfull": "https://img/1.jpg"},
        ],
    }
    base.update(overrides)
    return base


def _sample_df(keyword: str = "Japanese wall art"):
    now = int(time.time())
    raw_listings = [
        _make_raw_listing(
            listing_id=1,
            title="Japanese Wall Art Print",
            num_favorers=120,
            featured_rank=1,
            price={"amount": 2500, "divisor": 100, "currency_code": "USD"},
            shop_id=111,
            shop_name="ArtShopA",
            tags=["japanese", "wall art", "print", "minimalist"],
            last_modified_timestamp=now,
        ),
        _make_raw_listing(
            listing_id=2,
            title="Sumi-e Wall Decor",
            num_favorers=40,
            featured_rank=15,
            price={"amount": 4500, "divisor": 100, "currency_code": "USD"},
            shop_id=222,
            shop_name="ArtShopB",
            tags=["sumie", "wall decor"],
            images=[{"rank": 1, "hex_code": "333333", "brightness": 40, "url_fullxfull": "https://img/2.jpg"}],
            last_modified_timestamp=now - 86400 * 10,
        ),
        _make_raw_listing(
            listing_id=3,
            title="Cheap Japanese Poster",
            num_favorers=5,
            featured_rank=80,
            price={"amount": 800, "divisor": 100, "currency_code": "USD"},
            shop_id=333,
            shop_name="ArtShopC",
            tags=["japanese", "poster"],
            images=[],
            last_modified_timestamp=now - 86400 * 60,
        ),
        _make_raw_listing(
            listing_id=4,
            title="Another Art Piece",
            num_favorers=10,
            featured_rank=20,
            price={"amount": 1800, "divisor": 100, "currency_code": "USD"},
            shop_id=111,  # ArtShopAと同じショップ(集中度テスト用)
            shop_name="ArtShopA",
            tags=["japanese"],
            images=[],
            last_modified_timestamp=now - 86400 * 30,
        ),
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword=keyword)
    return analyzer.df


# ----------------------------------------------------------------------
# generate_ai_json: トップレベル構造
# ----------------------------------------------------------------------
def test_json_has_all_required_top_level_keys():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")

    required_keys = {
        "keyword",
        "generated_at",
        "total_count",
        "price_summary",
        "top_tags",
        "top_scored_listings",
        "top_favorited_listings",
        "shop_summary",
        "image_summary",
        "raw_listings_compact",
    }
    assert required_keys.issubset(set(data.keys()))


def test_json_is_serializable_without_numpy_types():
    """numpy/pandas型が混じったままjson.dumpsするとTypeErrorになるため、それが起きないこと。"""
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    serialized = json.dumps(data, ensure_ascii=False)
    assert isinstance(serialized, str)
    assert len(serialized) > 0


def test_json_contains_disclaimer_about_sales_data():
    """販売数ではなく公開データに基づく人気度推定であることが明記されていること。"""
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")

    assert data["disclaimer"] == DISCLAIMER
    assert "販売数" in data["disclaimer"]
    assert "推定" in data["disclaimer"]


def test_json_basic_fields():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")

    assert data["keyword"] == "Japanese wall art"
    assert data["total_count"] == 4
    # generated_atはISO8601形式の文字列であること
    assert "T" in data["generated_at"]


# ----------------------------------------------------------------------
# price_summary / shop_summary / image_summary
# ----------------------------------------------------------------------
def test_price_summary_values():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    summary = data["price_summary"]

    assert summary["min"] == 8.0
    assert summary["max"] == 45.0
    assert summary["currency_code"] == "USD"


def test_shop_summary_counts_unique_shops_and_concentration():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    shop_summary = data["shop_summary"]

    assert shop_summary["unique_shops"] == 3
    top_shops = {s["shop_name"]: s["listing_count"] for s in shop_summary["top_shops_by_listing_count"]}
    assert top_shops["ArtShopA"] == 2  # listing_id 1と4が同じショップ


def test_image_summary_has_expected_keys():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    image_summary = data["image_summary"]

    for key in ("mean", "median", "min", "max", "no_image_ratio", "full_image_ratio"):
        assert key in image_summary


# ----------------------------------------------------------------------
# top_tags / top_scored_listings / top_favorited_listings
# ----------------------------------------------------------------------
def test_top_tags_structure_and_ordering():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    top_tags = data["top_tags"]

    assert all(set(t.keys()) == {"tag", "count"} for t in top_tags)
    counts = [t["count"] for t in top_tags]
    assert counts == sorted(counts, reverse=True)
    # japaneseは3件のlistingに使われているため最頻出のはず
    assert top_tags[0]["tag"] == "japanese"
    assert top_tags[0]["count"] == 3


def test_top_scored_listings_sorted_desc_and_limited_to_10():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    top_scored = data["top_scored_listings"]

    assert len(top_scored) <= 10
    scores = [item["score"] for item in top_scored]
    assert scores == sorted(scores, reverse=True)
    assert top_scored[0]["title"] == "Japanese Wall Art Print"


def test_top_favorited_listings_sorted_desc():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    top_fav = data["top_favorited_listings"]

    favorers = [item["num_favorers"] for item in top_fav]
    assert favorers == sorted(favorers, reverse=True)
    assert top_fav[0]["title"] == "Japanese Wall Art Print"


# ----------------------------------------------------------------------
# raw_listings_compact
# ----------------------------------------------------------------------
def test_raw_listings_compact_has_exactly_required_fields():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    compact = data["raw_listings_compact"]

    expected_fields = {
        "title", "price", "currency_code", "shop_name", "num_favorers",
        "score", "tags", "description", "primary_image_url", "url",
    }
    assert len(compact) == 4
    for item in compact:
        assert set(item.keys()) == expected_fields


def test_raw_listings_compact_tags_is_a_list():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")
    first = data["raw_listings_compact"][0]

    assert isinstance(first["tags"], list)
    assert "japanese" in first["tags"]


def test_raw_listings_compact_description_truncated_to_500_chars():
    df = _sample_df()
    data = generate_ai_json(df, keyword="Japanese wall art")

    for item in data["raw_listings_compact"]:
        if item["description"] is not None:
            assert len(item["description"]) <= DESCRIPTION_MAX_CHARS


def test_raw_listings_compact_handles_missing_description():
    raw_listings = [_make_raw_listing(listing_id=1, description=None)]
    analyzer = EtsyAnalyzer(raw_listings, keyword="cat")
    data = generate_ai_json(analyzer.df, keyword="cat")

    assert data["raw_listings_compact"][0]["description"] is None


# ----------------------------------------------------------------------
# 空データ / エッジケース
# ----------------------------------------------------------------------
def test_generate_ai_json_handles_empty_dataframe():
    df = _sample_df()
    empty_df = df.iloc[0:0]
    data = generate_ai_json(empty_df, keyword="no such keyword")

    assert data["total_count"] == 0
    assert data["top_tags"] == []
    assert data["top_scored_listings"] == []
    assert data["top_favorited_listings"] == []
    assert data["raw_listings_compact"] == []
    assert data["shop_summary"]["unique_shops"] == 0
    # 空データでもjson.dumpsが例外にならないこと
    json.dumps(data, ensure_ascii=False)


# ----------------------------------------------------------------------
# save_ai_json
# ----------------------------------------------------------------------
def test_save_ai_json_creates_valid_json_file(tmp_path):
    df = _sample_df()
    path = save_ai_json(df, keyword="Japanese wall art", output_dir=str(tmp_path))

    assert path.endswith(".json")
    saved_path = Path(path)
    assert saved_path.exists()

    with open(saved_path, encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["keyword"] == "Japanese wall art"
    assert loaded["total_count"] == 4
    assert "販売数" in loaded["disclaimer"]


def test_save_ai_json_filename_sanitizes_keyword(tmp_path):
    df = _sample_df()
    path = save_ai_json(df, keyword="cat/mug?special", output_dir=str(tmp_path))

    filename = Path(path).name
    assert "/" not in filename
    assert "?" not in filename
    assert filename.endswith(".json")
