"""
prompt_builder.py
------------------
exporter.py が生成したJSON(dict)を受け取り、ChatGPT/Claude/Gemini等の
チャットAIにそのまま貼り付けて市場分析を依頼できるプロンプト(.txt)を
生成するモジュール (Phase5)。

exporter.pyまでのPhaseがデータの取得・集計・構造化を担当するのに対し、
prompt_builder.py は「そのデータをAIにどう分析してもらうか」という
依頼文(プロンプト)の組み立てだけに専念する。

使い方:
    from exporter import generate_ai_json
    from prompt_builder import save_analysis_prompt

    data = generate_ai_json(analyzer.df, keyword="cat mug")
    path = save_analysis_prompt(data, keyword="cat mug", output_dir="output")
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

DISCLAIMER_NOTE = (
    "このデータは実際の販売数ではありません。Etsyの公開API情報"
    "(お気に入り数・検索内の掲載順位・更新の新しさ・タグ/画像の充足度など)から"
    "算出した「人気度の推定値」です。分析・提案を行う際は、この前提を必ず"
    "踏まえてください。"
)

# 依頼する分析項目(要件の10項目)。この文言は tests/test_prompt_builder.py でも
# 完全一致でチェックしているため、変更する場合はテストも合わせて更新すること。
ANALYSIS_SECTIONS = [
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


def _build_data_summary(data: Dict[str, Any]) -> str:
    """JSON本体を貼り付ける前に、人間にもAIにも分かりやすい要約行を作る。"""
    keyword = data.get("keyword", "(不明)")
    total_count = data.get("total_count", 0)
    price_summary = data.get("price_summary", {}) or {}
    unique_shops = (data.get("shop_summary", {}) or {}).get("unique_shops", 0)

    lines = [
        f"- 検索キーワード: {keyword}",
        f"- 取得件数: {total_count}件",
        f"- ユニークショップ数: {unique_shops}店",
    ]

    price_min = price_summary.get("min")
    price_max = price_summary.get("max")
    currency = price_summary.get("currency_code", "")
    if price_min is not None and price_max is not None:
        lines.append(f"- 価格帯: {price_min} 〜 {price_max} {currency}")

    return "\n".join(lines)


def build_analysis_prompt(data: Dict[str, Any]) -> str:
    """
    exporter.generate_ai_json() の戻り値(dict)から、
    ChatGPT/Claude/Geminiに貼り付けられる市場分析プロンプト(文字列)を生成する。

    Args:
        data: exporter.generate_ai_json() が返すJSON(dict)

    Returns:
        プロンプト全文(プレーンテキスト)
    """
    keyword = data.get("keyword", "")
    data_summary = _build_data_summary(data)
    json_block = json.dumps(data, ensure_ascii=False, indent=2)

    numbered_sections = "\n".join(
        f"{i}. {section}" for i, section in enumerate(ANALYSIS_SECTIONS, start=1)
    )

    lines = [
        "あなたはEtsyの市場分析・商品企画に詳しいリサーチャーです。",
        f"以下は、Etsyで「{keyword}」というキーワードを検索して集計したデータです。",
        "",
        "# 重要な前提(必ず踏まえてください)",
        "",
        DISCLAIMER_NOTE,
        "",
        "# データ概要",
        "",
        data_summary,
        "",
        "# 分析対象データ(JSON)",
        "",
        "```json",
        json_block,
        "```",
        "",
        "# 依頼内容",
        "",
        "上記のデータをもとに、以下の項目についてそれぞれ見出しを立てて分析してください。",
        "「人気度スコア(score)」はあくまで公開データからの推定値であり、実際の売上を",
        "保証するものではない、という前提を踏まえたうえでコメントしてください。",
        "",
        numbered_sections,
        "",
        "# 出力形式",
        "",
        "- Markdown形式で、上記の項目ごとに見出し(##)を付けてください。",
        "- 「画像生成AI向けプロンプト案」は、Midjourney/Stable Diffusion等にそのまま",
        "  貼り付けられる英語のプロンプト例を2〜3案挙げてください。",
        "- 「Etsyタイトル案」「Etsyタグ案」は、それぞれ具体的な文字列の案を",
        "  複数(タイトルは3案程度、タグは13個まで)提示してください。",
        "- 断定的な売上予測ではなく、データから読み取れる傾向とその根拠をセットで",
        "  説明してください。",
    ]

    return "\n".join(lines)


def save_analysis_prompt(
    data: Dict[str, Any],
    keyword: Optional[str] = None,
    output_dir: str = "output",
    generated_at: Optional[datetime] = None,
) -> str:
    """
    build_analysis_prompt() の結果を .txt ファイルとして保存する。

    Args:
        data: exporter.generate_ai_json() が返すJSON(dict)
        keyword: ファイル名に使うキーワード(省略時はdata["keyword"]を使う)
        output_dir: 保存先ディレクトリ
        generated_at: 生成日時(省略時は現在時刻)

    Returns:
        保存したファイルのパス
    """
    keyword = keyword or data.get("keyword", "prompt")
    generated_at = generated_at or datetime.now()
    os.makedirs(output_dir, exist_ok=True)

    safe_keyword = "".join(c if c.isalnum() else "_" for c in keyword).strip("_")
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_keyword}_{timestamp}_prompt.txt"
    path = os.path.join(output_dir, filename)

    prompt_text = build_analysis_prompt(data)
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt_text)

    return path
