"""
tests/test_prompt_builder.py
-----------------------------
prompt_builder.build_analysis_prompt / save_analysis_prompt のユニットテスト。
"""

from __future__ import annotations

import time
from pathlib import Path

from analyzer import EtsyAnalyzer
from exporter import generate_ai_json
from prompt_builder import (
    ANALYSIS_SECTIONS,
    DISCLAIMER_NOTE,
    build_analysis_prompt,
    save_analysis_prompt,
)


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
        ],
    }
    base.update(overrides)
    return base


def _sample_ai_data(keyword: str = "Japanese wall art"):
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
            images=[],
            last_modified_timestamp=now - 86400 * 10,
        ),
    ]
    analyzer = EtsyAnalyzer(raw_listings, keyword=keyword)
    return generate_ai_json(analyzer.df, keyword=keyword)


# ----------------------------------------------------------------------
# build_analysis_prompt
# ----------------------------------------------------------------------
def test_prompt_contains_disclaimer_about_sales_data():
    """要件1: 販売数ではなく公開データによる人気度推定であることが明記されていること。"""
    data = _sample_ai_data()
    prompt = build_analysis_prompt(data)

    assert DISCLAIMER_NOTE in prompt
    assert "販売数ではありません" in prompt
    assert "人気度の推定値" in prompt


def test_prompt_contains_all_required_analysis_sections():
    """要件2〜11: 依頼する分析項目がすべてプロンプトに含まれていること。"""
    data = _sample_ai_data()
    prompt = build_analysis_prompt(data)

    required_sections = [
        "市場全体の要約",
        "売れ筋商品の共通点",
        "人気タグ分析",
        "価格帯分析",
        "競合の強さ",
        "参入余地",
        "狙うべき商品案",
        "避けるべき商品案",
        "画像生成AI向けプロンプト案",
        "Etsyタイトル案",
        "Etsyタグ案",
    ]
    for section in required_sections:
        assert section in prompt, f"'{section}' がプロンプトに含まれていません"

    # ANALYSIS_SECTIONS定数と要件リストが一致していることも確認
    assert set(ANALYSIS_SECTIONS) == set(required_sections)


def test_prompt_contains_keyword_and_data_summary():
    data = _sample_ai_data()
    prompt = build_analysis_prompt(data)

    assert "Japanese wall art" in prompt
    assert "取得件数: 2件" in prompt
    assert "ユニークショップ数: 2店" in prompt


def test_prompt_embeds_json_data():
    """AIが分析できるよう、元のJSONデータ本体がプロンプトに埋め込まれていること。"""
    data = _sample_ai_data()
    prompt = build_analysis_prompt(data)

    assert "```json" in prompt
    assert "top_scored_listings" in prompt
    assert "raw_listings_compact" in prompt
    assert "ArtShopA" in prompt  # JSON内のショップ名が含まれる


def test_prompt_numbers_sections_in_order():
    """依頼項目が番号付きリストで、要件の順序通りに並んでいること。"""
    data = _sample_ai_data()
    prompt = build_analysis_prompt(data)

    positions = [prompt.find(f"{i}. {section}") for i, section in enumerate(ANALYSIS_SECTIONS, start=1)]
    assert all(pos != -1 for pos in positions)
    assert positions == sorted(positions)


def test_prompt_handles_empty_data():
    """取得件数0件のデータでも例外にならないこと。"""
    empty_data = {
        "keyword": "no such keyword",
        "generated_at": "2026-01-01T00:00:00",
        "disclaimer": "dummy",
        "total_count": 0,
        "price_summary": {"min": None, "max": None, "mean": None, "median": None, "currency_code": "USD"},
        "top_tags": [],
        "top_scored_listings": [],
        "top_favorited_listings": [],
        "shop_summary": {"unique_shops": 0, "top_shops_by_listing_count": []},
        "image_summary": {},
        "raw_listings_compact": [],
    }
    prompt = build_analysis_prompt(empty_data)
    assert "no such keyword" in prompt
    assert "取得件数: 0件" in prompt


# ----------------------------------------------------------------------
# save_analysis_prompt
# ----------------------------------------------------------------------
def test_save_analysis_prompt_creates_txt_file(tmp_path):
    data = _sample_ai_data()
    path = save_analysis_prompt(data, keyword="Japanese wall art", output_dir=str(tmp_path))

    assert path.endswith("_prompt.txt")
    saved_path = Path(path)
    assert saved_path.exists()

    content = saved_path.read_text(encoding="utf-8")
    assert "Japanese wall art" in content
    assert DISCLAIMER_NOTE in content


def test_save_analysis_prompt_uses_keyword_from_data_when_not_specified(tmp_path):
    data = _sample_ai_data(keyword="fallback keyword")
    path = save_analysis_prompt(data, keyword=None, output_dir=str(tmp_path))

    filename = Path(path).name
    assert "fallback_keyword" in filename


def test_save_analysis_prompt_filename_sanitizes_keyword(tmp_path):
    data = _sample_ai_data()
    path = save_analysis_prompt(data, keyword="cat/mug?special", output_dir=str(tmp_path))

    filename = Path(path).name
    assert "/" not in filename
    assert "?" not in filename
    assert filename.endswith("_prompt.txt")
