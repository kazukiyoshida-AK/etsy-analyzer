"""
exporter.py
-----------
analyzer.py が生成した分析結果DataFrame(EtsyAnalyzer.df)を受け取り、
AI分析(LLM等)に渡しやすい形のJSONに変換・保存するモジュール (Phase4)。

reporter.py と同じ集計ロジック(価格帯統計・頻出タグ・スコア上位・
お気に入り数上位・画像枚数傾向)を再利用しつつ、人間が読むMarkdownではなく
プログラム(AI)が読みやすいJSON構造として出力する。

重要な注意:
本JSONに含まれる score・ランキング類は、公開API情報(お気に入り数・検索順位・
鮮度・タグ/画像の充足度など)から算出した「人気度の推定値」であり、実際の
販売数やレビュー評価を示すものではない。この注記は "disclaimer" キーとして
JSON自体にも必ず含める。

使い方:
    from exporter import save_ai_json
    path = save_ai_json(analyzer.df, keyword="cat mug", output_dir="output")
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from reporter import (
    _currency_label,
    _image_count_summary,
    _price_stats,
    _top_by_favorers,
    _top_by_score,
    _top_tags,
)

DISCLAIMER = (
    "本JSONのscore・ランキングは、公開Etsy API情報"
    "(お気に入り数・検索内の掲載順位・更新の新しさ・タグ/画像の充足度など)から"
    "算出した「人気度の推定値」です。実際の販売数やレビュー評価を示すものでは"
    "ありません。AI分析等で利用する際も、この前提を踏まえてください。"
)

# raw_listings_compact に含めるフィールドと出力順序
_COMPACT_FIELDS = [
    "title",
    "price",
    "currency_code",
    "shop_name",
    "num_favorers",
    "score",
    "tags",
    "description",
    "primary_image_url",
    "url",
]

DESCRIPTION_MAX_CHARS = 500


# ----------------------------------------------------------------------
# 内部ヘルパー
# ----------------------------------------------------------------------
def _to_native(value: Any) -> Any:
    """
    pandas/numpy型をJSONシリアライズ可能なPythonネイティブ型に変換する。
    NaN/NaTはNoneに変換する。
    """
    if value is None:
        return None
    if isinstance(value, (list, dict, str)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):  # numpy scalar (int64, float64 など)
        return value.item()
    return value


def _row_to_dict(row: pd.Series, columns: List[str]) -> Dict[str, Any]:
    return {col: _to_native(row.get(col)) for col in columns if col in row.index}


def _build_shop_summary(df: pd.DataFrame, top_n: int = 10) -> Dict[str, Any]:
    """
    ショップの集中度を把握するためのサマリーを作る。
    (今回の検索結果内での集計であり、Etsy全体の統計ではない)
    """
    if df.empty or "shop_id" not in df.columns:
        return {"unique_shops": 0, "top_shops_by_listing_count": []}

    unique_shops = int(df["shop_id"].nunique())

    if "shop_name" in df.columns:
        group_col = df["shop_name"].fillna(df["shop_id"].astype(str))
    else:
        group_col = df["shop_id"].astype(str)

    counts = group_col.value_counts().head(top_n)
    top_shops = [{"shop_name": name, "listing_count": int(count)} for name, count in counts.items()]

    return {"unique_shops": unique_shops, "top_shops_by_listing_count": top_shops}


def _build_price_summary(df: pd.DataFrame) -> Dict[str, Any]:
    stats = _price_stats(df)
    currency = _currency_label(df)
    return {
        "min": _to_native(stats["min"]),
        "max": _to_native(stats["max"]),
        "mean": _to_native(stats["mean"]),
        "median": _to_native(stats["median"]),
        "currency_code": currency,
    }


def _build_top_tags(df: pd.DataFrame, n: int = 20) -> List[Dict[str, Any]]:
    return [{"tag": tag, "count": int(count)} for tag, count in _top_tags(df, n=n)]


def _build_top_scored_listings(df: pd.DataFrame, n: int = 10) -> List[Dict[str, Any]]:
    top_df = _top_by_score(df, n=n)
    cols = [
        "listing_id", "title", "score", "price", "num_favorers",
        "featured_rank", "shop_name", "image_count", "tags", "url",
    ]
    cols = [c for c in cols if c in top_df.columns]
    return [_row_to_dict(row, cols) for _, row in top_df.iterrows()]


def _build_top_favorited_listings(df: pd.DataFrame, n: int = 10) -> List[Dict[str, Any]]:
    top_df = _top_by_favorers(df, n=n)
    cols = ["listing_id", "title", "num_favorers", "price", "shop_name", "url"]
    cols = [c for c in cols if c in top_df.columns]
    return [_row_to_dict(row, cols) for _, row in top_df.iterrows()]


def _build_image_summary(df: pd.DataFrame) -> Dict[str, Any]:
    summary = _image_count_summary(df)
    return {key: _to_native(value) for key, value in summary.items()}


def _tags_string_to_list(tags_str: Optional[str]) -> List[str]:
    if not tags_str or not isinstance(tags_str, str):
        return []
    return [t.strip() for t in tags_str.split(";") if t.strip()]


def _build_raw_listings_compact(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    AIに渡す前提で、必要最小限のフィールドだけに絞ったlisting一覧を作る。
    description は先頭500文字に切り詰める(トークン節約・出力肥大化防止)。
    """
    compact: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        description = row.get("description")
        if isinstance(description, str):
            description = description[:DESCRIPTION_MAX_CHARS]
        else:
            description = None

        item = {
            "title": _to_native(row.get("title")),
            "price": _to_native(row.get("price")),
            "currency_code": _to_native(row.get("currency_code")),
            "shop_name": _to_native(row.get("shop_name")),
            "num_favorers": _to_native(row.get("num_favorers")),
            "score": _to_native(row.get("score")),
            "tags": _tags_string_to_list(row.get("tags")),
            "description": description,
            "primary_image_url": _to_native(row.get("primary_image_url")),
            "url": _to_native(row.get("url")),
        }
        compact.append(item)

    return compact


# ----------------------------------------------------------------------
# 公開関数
# ----------------------------------------------------------------------
def generate_ai_json(
    df: pd.DataFrame,
    keyword: str,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    分析結果DataFrame(EtsyAnalyzer.df)から、AI分析に渡しやすいJSON構造(dict)を生成する。

    Args:
        df: EtsyAnalyzer.df (normalize_listing + score_listing 済みのDataFrame)
        keyword: 検索キーワード
        generated_at: 生成日時(省略時は現在時刻)

    Returns:
        JSONシリアライズ可能なdict
    """
    generated_at = generated_at or datetime.now()

    return {
        "keyword": keyword,
        "generated_at": generated_at.isoformat(),
        "disclaimer": DISCLAIMER,
        "total_count": int(len(df)),
        "price_summary": _build_price_summary(df),
        "top_tags": _build_top_tags(df, n=20),
        "top_scored_listings": _build_top_scored_listings(df, n=10),
        "top_favorited_listings": _build_top_favorited_listings(df, n=10),
        "shop_summary": _build_shop_summary(df),
        "image_summary": _build_image_summary(df),
        "raw_listings_compact": _build_raw_listings_compact(df),
    }


def save_ai_json(
    df: pd.DataFrame,
    keyword: str,
    output_dir: str = "output",
    generated_at: Optional[datetime] = None,
) -> str:
    """
    generate_ai_json() の結果を .json ファイルとして保存する。

    ファイル名は analyzer/reporter のCSV/Excel/Markdownと揃え、
    `キーワード_日時.json` の形式にする。

    Returns:
        保存したファイルのパス
    """
    generated_at = generated_at or datetime.now()
    os.makedirs(output_dir, exist_ok=True)

    safe_keyword = "".join(c if c.isalnum() else "_" for c in keyword).strip("_")
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_keyword}_{timestamp}.json"
    path = os.path.join(output_dir, filename)

    data = generate_ai_json(df, keyword, generated_at=generated_at)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path
