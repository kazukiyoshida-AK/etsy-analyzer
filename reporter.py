"""
reporter.py
-----------
analyzer.py が生成した分析結果DataFrame(EtsyAnalyzer.df)を受け取り、
Markdown形式の市場レポートを生成・保存するモジュール (Phase3)。

重要な注意:
本レポートに含まれる「人気度スコア」「お気に入り数TOP10」などのランキングは、
公開APIから取得できる情報(お気に入り数・検索順位・鮮度・タグ/画像充足度など)を
組み合わせた"人気度の推定値"であり、実際の販売数やレビュー評価を示すものでは
ない。この注記はレポート冒頭と「参入判断メモ」の両方に明記する。

使い方:
    from reporter import save_market_report
    path = save_market_report(analyzer.df, keyword="cat mug", output_dir="output")
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import os

import pandas as pd

DISCLAIMER = (
    "⚠️ **このレポートのスコア・ランキングは、公開API情報"
    "(お気に入り数・検索内の掲載順位・更新の新しさ・タグ/画像の充足度など)から"
    "算出した「人気度の推定値」です。実際の販売数やレビュー評価を示すものでは"
    "ありません。** 参考情報として活用し、最終判断はご自身の追加調査と合わせて"
    "行ってください。"
)

MAX_TAGS = 13
MAX_IMAGES = 10


# ----------------------------------------------------------------------
# 内部ヘルパー
# ----------------------------------------------------------------------
def _df_to_markdown_table(df: pd.DataFrame, columns: Optional[List[str]] = None) -> str:
    """
    pandas.DataFrameを手組みでMarkdownテーブル文字列に変換する。
    (tabulateパッケージへの依存を避けるため、to_markdown()は使わない)
    """
    if df.empty:
        return "_該当データがありません。_"

    cols = columns or list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    separator = "| " + " | ".join(["---"] * len(cols)) + " |"

    rows = []
    for _, row in df.iterrows():
        cells = []
        for col in cols:
            value = row.get(col)
            if isinstance(value, float):
                value = f"{value:.2f}"
            elif value is None or (isinstance(value, str) and not value):
                value = "-"
            cells.append(str(value))
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator] + rows)


def _price_stats(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    price_series = df["price"].dropna() if "price" in df.columns else pd.Series(dtype=float)
    if price_series.empty:
        return {"min": None, "max": None, "mean": None, "median": None}
    return {
        "min": price_series.min(),
        "max": price_series.max(),
        "mean": round(price_series.mean(), 2),
        "median": price_series.median(),
    }


def _currency_label(df: pd.DataFrame) -> str:
    if "currency_code" in df.columns:
        non_null = df["currency_code"].dropna()
        if not non_null.empty:
            return str(non_null.iloc[0])
    return "USD"


def _top_tags(df: pd.DataFrame, n: int = 20) -> List[Tuple[str, int]]:
    counter: Counter = Counter()
    if "tags" not in df.columns:
        return []
    for tags_str in df["tags"].dropna():
        for tag in [t.strip() for t in str(tags_str).split(";") if t.strip()]:
            counter[tag] += 1
    return counter.most_common(n)


def _top_by_score(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if "score" not in df.columns or df.empty:
        return df
    return df.sort_values("score", ascending=False).head(n)


def _top_by_favorers(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if "num_favorers" not in df.columns or df.empty:
        return df
    return df.sort_values("num_favorers", ascending=False).head(n)


def _price_band_counts(df: pd.DataFrame, bins: int = 6) -> pd.DataFrame:
    """
    価格帯別の商品数を集計する。
    Etsyは通貨・キーワードによって価格帯が大きく変わるため、
    固定の価格帯ではなくデータ範囲に応じた等間隔ビン(pd.cut)を使う。
    """
    price_series = df["price"].dropna() if "price" in df.columns else pd.Series(dtype=float)
    if price_series.empty:
        return pd.DataFrame(columns=["価格帯", "商品数"])

    if price_series.min() == price_series.max():
        label = f"{price_series.min():.2f}"
        return pd.DataFrame([{"価格帯": label, "商品数": len(price_series)}])

    cut = pd.cut(price_series, bins=bins)
    counts = cut.value_counts().sort_index()

    rows = []
    for interval, count in counts.items():
        label = f"{interval.left:.2f} 〜 {interval.right:.2f}"
        rows.append({"価格帯": label, "商品数": int(count)})
    return pd.DataFrame(rows)


def _image_count_summary(df: pd.DataFrame) -> Dict[str, Any]:
    if "image_count" not in df.columns or df.empty:
        return {}

    image_series = df["image_count"].fillna(0)
    no_image_ratio = (image_series == 0).mean() * 100 if len(image_series) else 0
    full_image_ratio = (image_series >= MAX_IMAGES).mean() * 100 if len(image_series) else 0

    return {
        "mean": round(image_series.mean(), 2),
        "median": image_series.median(),
        "min": image_series.min(),
        "max": image_series.max(),
        "no_image_ratio": round(no_image_ratio, 1),
        "full_image_ratio": round(full_image_ratio, 1),
    }


def _entry_memo(
    df: pd.DataFrame,
    price_stats: Dict[str, Optional[float]],
    image_summary: Dict[str, Any],
    top_tags: List[Tuple[str, int]],
) -> List[str]:
    """
    集計結果から簡易的な「参入判断メモ」を自動生成する。
    ここでのコメントはあくまで機械的なヒューリスティックであり、
    販売数などの裏付けがあるわけではない点に注意(disclaimer参照)。
    """
    memo: List[str] = []
    count = len(df)

    if count == 0:
        return ["取得件数が0件のため、参入判断の材料がありません。別のキーワードを試してください。"]

    # 競合の分散度合い (ユニークショップ数 / 商品数)
    unique_shops = df["shop_id"].nunique() if "shop_id" in df.columns else 0
    if count > 0:
        shop_ratio = unique_shops / count
        if shop_ratio > 0.8:
            memo.append(
                f"競合ショップは{unique_shops}店と分散しており、特定の強い寡占ショップは"
                "少ない可能性があります(新規参入の障壁は比較的低いかもしれません)。"
            )
        elif shop_ratio < 0.3:
            memo.append(
                f"取得{count}件に対しユニークショップ数が{unique_shops}店と少なく、"
                "一部のショップが多くの商品を出品している(寡占気味の)可能性があります。"
            )
        else:
            memo.append(f"競合ショップ数は{unique_shops}店で、分散・寡占のどちらとも言えない状況です。")

    # 価格帯の広がり
    if price_stats.get("min") is not None and price_stats.get("max") is not None:
        price_min, price_max = price_stats["min"], price_stats["max"]
        if price_min > 0:
            spread_ratio = price_max / price_min
            if spread_ratio >= 5:
                memo.append(
                    f"価格帯は{price_min:.2f}〜{price_max:.2f}と非常に幅広く、"
                    "低価格戦略・高価格(ブランド)戦略のどちらの余地もありそうです。"
                )
            else:
                memo.append(
                    f"価格帯は{price_min:.2f}〜{price_max:.2f}とある程度収束しており、"
                    "この価格帯から大きく外れると競争力が下がる可能性があります。"
                )

    # 画像投資の水準
    if image_summary:
        avg_images = image_summary.get("mean")
        full_ratio = image_summary.get("full_image_ratio", 0)
        if avg_images is not None:
            if full_ratio >= 40:
                memo.append(
                    f"上位競合の画像枚数は平均{avg_images}枚、"
                    f"上限({MAX_IMAGES}枚)まで使っている商品も{full_ratio}%あり、"
                    "画像への投資水準が高い(参入時に相応のクオリティが必要な)市場と考えられます。"
                )
            else:
                memo.append(
                    f"画像枚数は平均{avg_images}枚で、上限({MAX_IMAGES}枚)まで使っている商品は"
                    f"{full_ratio}%に留まります。画像を充実させることで相対的に差別化できる余地が"
                    "あるかもしれません。"
                )

    # タグの集中度
    if top_tags:
        top_tag, top_tag_count = top_tags[0]
        if count > 0 and (top_tag_count / count) >= 0.5:
            memo.append(
                f"最頻出タグ「{top_tag}」は取得商品の{round(top_tag_count / count * 100, 1)}%で"
                "使われており、SEO的なキーワードの型がある程度固まっている可能性があります。"
            )

    memo.append(
        "上記はいずれも公開データからの機械的な推定であり、実際の売れ行きを保証するもの"
        "ではありません。参入判断の一次情報として活用し、必要に応じて追加調査を行ってください。"
    )
    return memo


# ----------------------------------------------------------------------
# 公開関数
# ----------------------------------------------------------------------
def generate_market_report(
    df: pd.DataFrame,
    keyword: str,
    generated_at: Optional[datetime] = None,
) -> str:
    """
    分析結果DataFrame(EtsyAnalyzer.df)からMarkdown形式の市場レポートを生成する。

    Args:
        df: EtsyAnalyzer.df (normalize_listing + score_listing 済みのDataFrame)
        keyword: 検索キーワード(レポートのタイトル・見出しに使用)
        generated_at: レポート生成日時(省略時は現在時刻)

    Returns:
        Markdown形式のレポート文字列
    """
    generated_at = generated_at or datetime.now()
    currency = _currency_label(df)
    count = len(df)

    price_stats = _price_stats(df)
    top_tags = _top_tags(df, n=20)
    top_score_df = _top_by_score(df, n=10)
    top_fav_df = _top_by_favorers(df, n=10)
    price_bands = _price_band_counts(df)
    image_summary = _image_count_summary(df)
    entry_memo = _entry_memo(df, price_stats, image_summary, top_tags)

    lines: List[str] = []

    # --- タイトル / 概要 ---
    lines.append(f"# Etsy市場レポート: 「{keyword}」")
    lines.append("")
    lines.append(f"生成日時: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")

    lines.append("## 概要")
    lines.append("")
    lines.append(f"- 検索キーワード: **{keyword}**")
    lines.append(f"- 取得件数: **{count}件**")
    if price_stats["min"] is not None:
        lines.append(
            f"- 価格帯: {price_stats['min']:.2f} 〜 {price_stats['max']:.2f} {currency}"
        )
        lines.append(f"- 平均価格: {price_stats['mean']:.2f} {currency}")
        lines.append(f"- 中央値価格: {price_stats['median']:.2f} {currency}")
    else:
        lines.append("- 価格帯 / 平均価格 / 中央値価格: データなし")
    unique_shops = df["shop_id"].nunique() if "shop_id" in df.columns else 0
    lines.append(f"- ユニークショップ数: **{unique_shops}店**")
    lines.append("")

    # --- 人気タグ TOP20 ---
    lines.append("## 人気タグ TOP20")
    lines.append("")
    if top_tags:
        tag_df = pd.DataFrame(top_tags, columns=["タグ", "出現数"])
        lines.append(_df_to_markdown_table(tag_df))
    else:
        lines.append("_タグ情報がありません。_")
    lines.append("")

    # --- スコア上位10件 ---
    lines.append("## スコア上位10件(人気度推定・スコア降順)")
    lines.append("")
    score_cols = [
        "score", "title", "price", "num_favorers", "featured_rank",
        "shop_name", "image_count", "tags",
    ]
    score_cols = [c for c in score_cols if c in top_score_df.columns]
    lines.append(_df_to_markdown_table(top_score_df, columns=score_cols))
    lines.append("")

    # --- 価格帯別の商品数 ---
    lines.append("## 価格帯別の商品数")
    lines.append("")
    lines.append(_df_to_markdown_table(price_bands))
    lines.append("")

    # --- お気に入り数TOP10 ---
    lines.append("## お気に入り数 TOP10")
    lines.append("")
    fav_cols = ["title", "num_favorers", "price", "shop_name", "url"]
    fav_cols = [c for c in fav_cols if c in top_fav_df.columns]
    lines.append(_df_to_markdown_table(top_fav_df, columns=fav_cols))
    lines.append("")

    # --- 画像枚数の傾向 ---
    lines.append("## 画像枚数の傾向")
    lines.append("")
    if image_summary:
        lines.append(f"- 平均画像枚数: {image_summary['mean']}枚")
        lines.append(f"- 中央値: {image_summary['median']}枚")
        lines.append(f"- 最小 / 最大: {image_summary['min']}枚 / {image_summary['max']}枚")
        lines.append(f"- 画像0枚の商品の割合: {image_summary['no_image_ratio']}%")
        lines.append(f"- 上限({MAX_IMAGES}枚)まで使っている商品の割合: {image_summary['full_image_ratio']}%")
    else:
        lines.append("_画像情報がありません(--skip-enrich で実行した場合など)。_")
    lines.append("")

    # --- 参入判断メモ ---
    lines.append("## 参入判断メモ")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")
    for memo_line in entry_memo:
        lines.append(f"- {memo_line}")
    lines.append("")

    return "\n".join(lines)


def save_market_report(
    df: pd.DataFrame,
    keyword: str,
    output_dir: str = "output",
    generated_at: Optional[datetime] = None,
) -> str:
    """
    generate_market_report() の結果を .md ファイルとして保存する。

    ファイル名は analyzer/main.py のCSV/Excelと揃え、
    `キーワード_日時_report.md` の形式にする。

    Returns:
        保存したファイルのパス
    """
    generated_at = generated_at or datetime.now()
    os.makedirs(output_dir, exist_ok=True)

    safe_keyword = "".join(c if c.isalnum() else "_" for c in keyword).strip("_")
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_keyword}_{timestamp}_report.md"
    path = os.path.join(output_dir, filename)

    markdown = generate_market_report(df, keyword, generated_at=generated_at)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return path
