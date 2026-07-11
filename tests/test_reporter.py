"""
tests/test_reporter.py
-----------------------
reporter.generate_market_report / save_market_report のユニットテスト。
"""

from __future__ import annotations

import time

from analyzer import EtsyAnalyzer
from reporter import DISCLAIMER, generate_market_report, save_market_report


def _make_raw_listing(**overrides):
    now = int(time.time())
    base = {
        "listing_id": 1,
        "title": "Japanese Wall Art Print",
        "url": "https://etsy.com/listing/1",
        "description": "A beautiful minimalist Japanese wall art print",
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
            {"rank": 2, "hex_code": "eeeeee", "brightness": 220, "url_fullxfull": "https://img/1b.jpg"},
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
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword=keyword)
    return analyzer.df


# ----------------------------------------------------------------------
# generate_market_report
# ----------------------------------------------------------------------
def test_report_contains_all_required_sections():
    df = _sample_df()
    report = generate_market_report(df, keyword="Japanese wall art")

    required_sections = [
        "# Etsy市場レポート",
        "## 概要",
        "## 人気タグ TOP20",
        "## スコア上位10件",
        "## 価格帯別の商品数",
        "## お気に入り数 TOP10",
        "## 画像枚数の傾向",
        "## 参入判断メモ",
    ]
    for section in required_sections:
        assert section in report, f"セクション '{section}' がレポートに含まれていません"


def test_report_contains_keyword_and_count():
    df = _sample_df()
    report = generate_market_report(df, keyword="Japanese wall art")

    assert "Japanese wall art" in report
    assert "取得件数: **3件**" in report
    assert "ユニークショップ数: **3店**" in report


def test_report_contains_disclaimer_about_sales_data():
    """
    販売数ではなく、公開データに基づく人気度推定レポートであることが
    Markdown内に明記されていることを確認する(重要な要件)。
    """
    df = _sample_df()
    report = generate_market_report(df, keyword="Japanese wall art")

    assert DISCLAIMER in report
    # disclaimerが概要セクションの前と参入判断メモの両方に出ていること
    assert report.count(DISCLAIMER) >= 2
    assert "実際の販売数" in report


def test_report_price_stats_are_correct():
    df = _sample_df()
    report = generate_market_report(df, keyword="Japanese wall art")

    assert "8.00" in report  # 最安値
    assert "45.00" in report  # 最高値


def test_report_top_score_table_has_highest_scoring_item_first():
    df = _sample_df()
    report = generate_market_report(df, keyword="Japanese wall art")

    score_section = report.split("## スコア上位10件")[1].split("## 価格帯別の商品数")[0]
    # 最もお気に入り数・掲載順位が良い商品が最初の行に来ること
    first_row_index = score_section.find("Japanese Wall Art Print")
    second_row_index = score_section.find("Sumi-e Wall Decor")
    assert first_row_index != -1
    assert second_row_index != -1
    assert first_row_index < second_row_index


def test_report_handles_empty_dataframe():
    df = _sample_df()
    empty_df = df.iloc[0:0]
    report = generate_market_report(empty_df, keyword="no such keyword")

    assert "no such keyword" in report
    assert "取得件数: **0件**" in report
    # 空データでも例外にならず、参入判断メモに適切なメッセージが出ること
    assert "取得件数が0件のため" in report


def test_report_handles_missing_image_data():
    """画像情報が全くない(image_countが常に0)場合でも例外にならないこと。"""
    df = _sample_df()
    df = df.copy()
    df["image_count"] = 0
    report = generate_market_report(df, keyword="Japanese wall art")
    assert "画像枚数の傾向" in report


# ----------------------------------------------------------------------
# save_market_report
# ----------------------------------------------------------------------
def test_save_market_report_creates_md_file(tmp_path):
    df = _sample_df()
    path = save_market_report(df, keyword="Japanese wall art", output_dir=str(tmp_path))

    assert path.endswith(".md")
    assert path.endswith("_report.md")

    from pathlib import Path
    saved_path = Path(path)
    assert saved_path.exists()

    content = saved_path.read_text(encoding="utf-8")
    assert "# Etsy市場レポート" in content
    assert "Japanese wall art" in content


def test_save_market_report_filename_contains_sanitized_keyword(tmp_path):
    df = _sample_df()
    path = save_market_report(df, keyword="cat/mug?special", output_dir=str(tmp_path))

    filename = path.split("/")[-1]
    # スラッシュや?などのファイル名に使えない文字が除去/置換されていること
    assert "/" not in filename.replace(str(tmp_path), "")
    assert "?" not in filename
