"""
main.py
-------
Etsy分析ツールのエントリーポイント。

--source {api,csv,html,json} で商品データの取得方法を切り替えられる
(interfaces.DataSource経由)。既定は "api" で、これは旧バージョンの
main.pyと同じ挙動(Etsy Open APIをキーワード検索)を維持する
(後方互換)。

流れ:
  1. --source に応じたDataSourceを構築し、fetch_listings()で
     canonical schema (interfaces.schema.Listing) のリストを取得
  2. adapter.build_analyzer() で canonical Listing を既存の
     EtsyAnalyzerへ変換(analyzer.py自体はinterfacesに依存しない)
  3. CSV / Excel に保存 (人気度スコア降順)
  4. --report 指定時、Markdown市場レポート(.md)を保存
  5. --json 指定時、AI分析向けJSON(.json)を保存
  6. --prompt 指定時、AI分析用プロンプト(.txt)を保存
  7. 基本統計 + スコア上位商品をコンソールに表示

使い方:
  # 従来通り(Etsy Open API。後方互換。ETSY_API_KEYが必要)
  python main.py --keyword "cat mug" --max-results 50
  python main.py --keyword "cat mug" --skip-enrich   # ショップ/画像情報の取得をスキップ
  python main.py --keyword "cat mug" --report --json --prompt

  # canonical schema準拠CSVから読み込む場合
  python main.py --source csv --input data/listings.csv --keyword "cat mug"

  # 任意列名のCSV + マッピングファイル({"canonical_field": "csv列名"}形式のJSON)
  python main.py --source csv --input data/listings.csv --mapping mapping.json

  # 保存済みHTML(検索エンジン向け構造化データを含む商品ページ)から読み込む場合
  python main.py --source html --input saved_page.html --keyword "cat mug"

  # JSONから読み込む場合
  python main.py --source json --input data/listings.json --keyword "cat mug"

  python main.py   # --keyword省略時は対話的にキーワードを聞かれる(全source共通)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from dotenv import load_dotenv

from adapter import build_analyzer
from exporter import generate_ai_json, save_ai_json
from interfaces.datasource import (
    CSVDataSource,
    DataSource,
    DataSourceError,
    EtsyAPIDataSource,
    HTMLDataSource,
    JSONDataSource,
)
from interfaces.schema import Listing, ValidationError, validate_listing
from prompt_builder import save_analysis_prompt
from reporter import save_market_report

OUTPUT_DIR = "output"
SOURCE_CHOICES = ["api", "csv", "html", "json"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Etsy商品分析ツール")
    parser.add_argument(
        "--source",
        type=str,
        default="api",
        choices=SOURCE_CHOICES,
        help="データ取得方法 (デフォルト: api = 従来通りEtsy Open APIを使用。後方互換)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="csv/html/jsonソース使用時の入力ファイルパス(該当sourceでは必須)",
    )
    parser.add_argument(
        "--mapping",
        type=str,
        default=None,
        help=(
            "csvソース使用時、任意列名からcanonical schemaへの対応を書いた"
            'JSONファイルのパス(任意。形式: {"canonical_field": "csv列名"})'
        ),
    )
    parser.add_argument("--keyword", "-k", type=str, default=None, help="検索キーワード")
    parser.add_argument(
        "--max-results",
        "-n",
        type=int,
        default=50,
        help="取得する商品件数の上限 (デフォルト: 50)",
    )
    parser.add_argument(
        "--sort-on",
        type=str,
        default="score",
        choices=["score", "created", "price", "updated"],
        help="並び替え基準 (apiソースのみ有効。デフォルト: score)",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="ショップ情報・画像情報の取得(追加API呼び出し)をスキップする(apiソースのみ有効)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="分析結果からMarkdown形式の市場レポート(.md)も生成する",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="分析結果からAI分析向けJSON(.json)も生成する",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="分析結果からAIに貼り付けられる市場分析プロンプト(.txt)を生成する",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> Optional[str]:
    """
    --source と --input / --mapping の組み合わせを検証する。

    Returns:
        問題があればエラーメッセージ(str)、問題なければNone。
    """
    if args.source == "api":
        if args.input is not None:
            return "--source api では --input は使用できません(--keywordを指定してください)。"
        if args.mapping is not None:
            return "--source api では --mapping は使用できません。"
        return None

    if args.input is None:
        return f"--source {args.source} を使う場合は --input が必須です。"

    if args.mapping is not None and args.source != "csv":
        return "--mapping は --source csv の場合のみ指定できます。"

    return None


def get_keyword(args: argparse.Namespace) -> str:
    if args.keyword:
        return args.keyword.strip()

    keyword = input("検索キーワードを入力してください: ").strip()
    if not keyword:
        print("キーワードが入力されませんでした。処理を終了します。")
        sys.exit(1)
    return keyword


def build_output_paths(keyword: str) -> Tuple[str, str]:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_keyword = "".join(c if c.isalnum() else "_" for c in keyword).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{safe_keyword}_{timestamp}"
    csv_path = os.path.join(OUTPUT_DIR, f"{base_name}.csv")
    xlsx_path = os.path.join(OUTPUT_DIR, f"{base_name}.xlsx")
    return csv_path, xlsx_path


def print_summary(stats: dict) -> None:
    print("\n=== 分析サマリー ===")
    print(f"取得件数     : {stats.get('count')}")
    print(f"最安値       : {stats.get('price_min')}")
    print(f"最高値       : {stats.get('price_max')}")
    print(f"平均価格     : {stats.get('price_mean')}")
    print(f"中央値       : {stats.get('price_median')}")
    print(f"ユニークショップ数: {stats.get('unique_shops')}")

    top_tags = stats.get("top_tags", [])
    if top_tags:
        print("\n--- 頻出タグ TOP10 ---")
        for tag, count in top_tags[:10]:
            print(f"  {tag}: {count}")


def print_top_listings(analyzer, n: int = 10) -> None:
    top_df = analyzer.top_listings(n)
    if top_df.empty:
        return

    print(f"\n--- 人気度スコア TOP{n} (推定値。販売数・レビューではない点に注意) ---")
    for _, row in top_df.iterrows():
        shop = row.get("shop_name") or f"shop_id={row.get('shop_id')}"
        print(f"  [{row.get('score')}] {row.get('title')} ({shop})")


def _load_mapping(path: str) -> dict:
    """--mapping で指定されたJSONファイルを読み込み、column_mapping辞書を返す。"""
    try:
        with open(path, encoding="utf-8") as f:
            mapping = json.load(f)
    except OSError as exc:
        raise DataSourceError(f"--mapping ファイルの読み込みに失敗しました: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DataSourceError(f"--mapping ファイルの解析に失敗しました: {exc}") from exc

    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise DataSourceError(
            '--mapping ファイルは {"canonical_field": "csv列名", ...} 形式の'
            "JSONオブジェクトである必要があります。"
        )
    return mapping


def find_invalid_listings(listings: List[Listing]) -> List[Tuple[int, List[ValidationError]]]:
    """
    listings(canonical schema想定)を検証し、違反のあった
    (インデックス, ValidationErrorのリスト) のリストを返す。
    違反がなければ空リスト。
    """
    invalid: List[Tuple[int, List[ValidationError]]] = []
    for idx, listing in enumerate(listings):
        errors = validate_listing(listing)
        if errors:
            invalid.append((idx, errors))
    return invalid


def print_invalid_listings(
    invalid: List[Tuple[int, List[ValidationError]]], limit: int = 10
) -> None:
    """find_invalid_listings()の結果を、人が読める形でコンソールに表示する。"""
    print("エラー: 取得したデータがcanonical schemaに違反しています。")
    for idx, errors in invalid[:limit]:
        print(f"  [{idx}件目]")
        for err in errors:
            print(f"    - {err}")

    remaining = len(invalid) - limit
    if remaining > 0:
        print(f"  ...他 {remaining} 件のlistingにも違反があります。")


def build_datasource(args: argparse.Namespace) -> DataSource:
    """--source に応じたDataSource実装を構築する。"""
    if args.source == "api":
        return EtsyAPIDataSource()

    if args.source == "csv":
        mapping = _load_mapping(args.mapping) if args.mapping else None
        return CSVDataSource(args.input, column_mapping=mapping)

    if args.source == "html":
        return HTMLDataSource(args.input)

    if args.source == "json":
        return JSONDataSource(args.input)

    raise DataSourceError(f"未対応のsourceです: {args.source}")


def main() -> None:
    load_dotenv()
    args = parse_args()

    validation_error = validate_args(args)
    if validation_error:
        print(f"エラー: {validation_error}")
        sys.exit(1)

    keyword = get_keyword(args)

    total_steps = 3 + int(args.report) + int(args.json) + int(args.prompt)
    step = 0

    step += 1
    print(f"\n[{step}/{total_steps}] データ取得中 (source={args.source})...")
    try:
        with build_datasource(args) as source:
            listings = source.fetch_listings(
                keyword=keyword,
                max_results=args.max_results,
                sort_on=args.sort_on,
                skip_enrich=args.skip_enrich,
            )
    except DataSourceError as exc:
        print(f"エラー: {exc}")
        sys.exit(1)

    if not listings:
        print("該当する商品が見つかりませんでした。")
        sys.exit(0)

    print(f"  -> {len(listings)} 件取得しました。")

    invalid_listings = find_invalid_listings(listings)
    if invalid_listings:
        print_invalid_listings(invalid_listings)
        sys.exit(1)

    step += 1
    print(f"[{step}/{total_steps}] データを分析中 (スコア計算含む)...")
    analyzer = build_analyzer(listings, keyword=keyword)
    stats = analyzer.basic_stats()

    step += 1
    print(f"[{step}/{total_steps}] CSV / Excel に保存中...")
    csv_path, xlsx_path = build_output_paths(keyword)
    analyzer.save_csv(csv_path)
    analyzer.save_excel(xlsx_path)

    print(f"  -> CSV : {csv_path}")
    print(f"  -> Excel: {xlsx_path}")

    if args.report:
        step += 1
        print(f"[{step}/{total_steps}] Markdown市場レポートを生成中...")
        report_path = save_market_report(analyzer.df, keyword=keyword, output_dir=OUTPUT_DIR)
        print(f"  -> Report: {report_path}")

    if args.json:
        step += 1
        print(f"[{step}/{total_steps}] AI分析向けJSONを生成中...")
        json_path = save_ai_json(analyzer.df, keyword=keyword, output_dir=OUTPUT_DIR)
        print(f"  -> JSON: {json_path}")

    if args.prompt:
        step += 1
        print(f"[{step}/{total_steps}] AI分析用プロンプトを生成中...")
        ai_data = generate_ai_json(analyzer.df, keyword=keyword)
        prompt_path = save_analysis_prompt(ai_data, keyword=keyword, output_dir=OUTPUT_DIR)
        print(f"  -> Prompt: {prompt_path}")

    print_summary(stats)
    print_top_listings(analyzer)


if __name__ == "__main__":
    main()
