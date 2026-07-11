"""
tests/test_analyzer.py
-----------------------
analyzer.EtsyAnalyzer / normalize_listing のユニットテスト。
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from analyzer import EtsyAnalyzer, normalize_listing


def _make_raw_listing(**overrides):
    """テスト用のenrich済みlisting生データを組み立てるヘルパー。"""
    base = {
        "listing_id": 1,
        "title": "Cat Mug Handmade",
        "url": "https://etsy.com/listing/1",
        "description": "A cute cat mug for cat lovers",
        "price": {"amount": 1999, "divisor": 100, "currency_code": "USD"},
        "quantity": 5,
        "tags": ["cat", "mug", "gift"],
        "materials": ["ceramic"],
        "shop_id": 111,
        "shop_name": "CatShop",
        "shop_url": "https://etsy.com/shop/CatShop",
        "num_favorers": 50,
        "featured_rank": 2,
        "when_made": "2020_2024",
        "who_made": "i_did",
        "is_customizable": True,
        "taxonomy_id": 1,
        "creation_timestamp": int(time.time()) - 1000,
        "last_modified_timestamp": int(time.time()),
        "images": [
            {
                "listing_id": 1,
                "rank": 1,
                "hex_code": "ff0000",
                "brightness": 120,
                "url_570xN": "https://img/1_570.jpg",
                "url_fullxfull": "https://img/1_full.jpg",
            },
            {
                "listing_id": 1,
                "rank": 2,
                "hex_code": "00ff00",
                "brightness": 200,
                "url_570xN": "https://img/1_570_2.jpg",
            },
        ],
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# normalize_listing
# ----------------------------------------------------------------------
def test_normalize_listing_basic_fields():
    raw = _make_raw_listing()
    row = normalize_listing(raw)

    assert row["listing_id"] == 1
    assert row["title"] == "Cat Mug Handmade"
    assert row["price"] == pytest.approx(19.99)
    assert row["currency_code"] == "USD"
    assert row["tags"] == "cat; mug; gift"
    assert row["tag_count"] == 3
    assert row["materials"] == "ceramic"


def test_normalize_listing_phase2_fields():
    """Phase2で追加したショップ/画像関連フィールドを検証する。"""
    raw = _make_raw_listing()
    row = normalize_listing(raw)

    assert row["shop_name"] == "CatShop"
    assert row["shop_url"] == "https://etsy.com/shop/CatShop"
    # rankが最小(1)の画像が代表画像として選ばれること
    assert row["primary_image_url"] == "https://img/1_full.jpg"
    assert row["image_count"] == 2
    assert row["image_color_hex"] == "ff0000"
    assert row["image_brightness"] == 120


def test_normalize_listing_handles_missing_optional_data():
    """shop_name/imagesが無いデータでも例外にならずNone/空値になること。"""
    raw = _make_raw_listing(shop_name=None, shop_url=None, images=[])
    row = normalize_listing(raw)

    assert row["shop_name"] is None
    assert row["primary_image_url"] is None
    assert row["image_count"] == 0
    assert row["image_color_hex"] is None
    assert row["image_brightness"] is None


def test_normalize_listing_handles_missing_price():
    raw = _make_raw_listing(price={})
    row = normalize_listing(raw)
    assert row["price"] is None


# ----------------------------------------------------------------------
# EtsyAnalyzer.basic_stats
# ----------------------------------------------------------------------
def test_basic_stats_empty():
    analyzer = EtsyAnalyzer([])
    stats = analyzer.basic_stats()
    assert stats == {"count": 0}


def test_basic_stats_values():
    raw_listings = [
        _make_raw_listing(listing_id=1, price={"amount": 1000, "divisor": 100, "currency_code": "USD"}),
        _make_raw_listing(listing_id=2, price={"amount": 2000, "divisor": 100, "currency_code": "USD"}, shop_id=222),
    ]
    analyzer = EtsyAnalyzer(raw_listings)
    stats = analyzer.basic_stats()

    assert stats["count"] == 2
    assert stats["price_min"] == pytest.approx(10.0)
    assert stats["price_max"] == pytest.approx(20.0)
    assert stats["unique_shops"] == 2
    assert ("cat", 2) in stats["top_tags"]


# ----------------------------------------------------------------------
# EtsyAnalyzer.score_listing
# ----------------------------------------------------------------------
def test_score_is_within_0_to_100():
    now = int(time.time())
    raw_listings = [
        _make_raw_listing(listing_id=1, num_favorers=100, featured_rank=1, last_modified_timestamp=now),
        _make_raw_listing(listing_id=2, num_favorers=1, featured_rank=99, last_modified_timestamp=now - 86400 * 60),
        _make_raw_listing(listing_id=3, num_favorers=50, featured_rank=50, last_modified_timestamp=now - 86400 * 10),
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword="cat")

    assert "score" in analyzer.df.columns
    assert analyzer.df["score"].between(0, 100).all()


def test_score_ranks_better_listing_higher():
    """お気に入り数・掲載順位・鮮度すべてで優位な商品の方がスコアが高くなること。"""
    now = int(time.time())
    strong = _make_raw_listing(
        listing_id=1,
        title="Cat Mug",
        num_favorers=200,
        featured_rank=1,
        last_modified_timestamp=now,
        tags=["cat", "mug", "gift", "ceramic"],
    )
    weak = _make_raw_listing(
        listing_id=2,
        title="Dog Bowl",
        num_favorers=1,
        featured_rank=100,
        last_modified_timestamp=now - 86400 * 90,
        tags=["dog"],
        images=[],  # 画像なし
        description="dog bowl",
    )

    analyzer = EtsyAnalyzer([strong, weak], keyword="cat")
    strong_score = analyzer.df.loc[analyzer.df["listing_id"] == 1, "score"].iloc[0]
    weak_score = analyzer.df.loc[analyzer.df["listing_id"] == 2, "score"].iloc[0]

    assert strong_score > weak_score


def test_score_neutral_without_keyword():
    """keywordを指定しなくてもエラーにならず、スコアが計算されること。"""
    raw_listings = [_make_raw_listing(listing_id=1), _make_raw_listing(listing_id=2, shop_id=222)]
    analyzer = EtsyAnalyzer(raw_listings)  # keyword未指定
    assert analyzer.df["score"].between(0, 100).all()


def test_top_listings_sorted_descending():
    now = int(time.time())
    raw_listings = [
        _make_raw_listing(listing_id=1, num_favorers=10, featured_rank=50, last_modified_timestamp=now - 86400),
        _make_raw_listing(listing_id=2, num_favorers=200, featured_rank=1, last_modified_timestamp=now),
        _make_raw_listing(listing_id=3, num_favorers=50, featured_rank=20, last_modified_timestamp=now - 86400 * 5),
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword="cat")
    top = analyzer.top_listings(n=3)

    scores = top["score"].tolist()
    assert scores == sorted(scores, reverse=True)


# ----------------------------------------------------------------------
# 保存機能 (CSV / Excel)
# ----------------------------------------------------------------------
def test_save_csv_creates_file_and_is_sorted(tmp_path):
    now = int(time.time())
    raw_listings = [
        _make_raw_listing(listing_id=1, num_favorers=1, featured_rank=99, last_modified_timestamp=now - 86400 * 90),
        _make_raw_listing(listing_id=2, num_favorers=500, featured_rank=1, last_modified_timestamp=now),
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword="cat")

    csv_path = tmp_path / "result.csv"
    analyzer.save_csv(str(csv_path))

    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert len(df) == 2
    # スコア降順で保存されていること(1行目が2番目に強いlisting_id=2のはず)
    assert df.iloc[0]["listing_id"] == 2


def test_save_excel_creates_file_with_expected_sheets(tmp_path):
    raw_listings = [
        _make_raw_listing(listing_id=1),
        _make_raw_listing(listing_id=2, shop_id=222),
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword="cat")

    xlsx_path = tmp_path / "result.xlsx"
    analyzer.save_excel(str(xlsx_path))

    assert xlsx_path.exists()
    sheets = pd.read_excel(xlsx_path, sheet_name=None)
    assert set(sheets.keys()) == {"listings", "summary", "top_tags"}
    assert "score" in sheets["listings"].columns
    assert "shop_name" in sheets["listings"].columns
    assert "primary_image_url" in sheets["listings"].columns
