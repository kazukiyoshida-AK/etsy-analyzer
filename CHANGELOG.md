# Changelog

このプロジェクトの変更履歴です。フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に準拠します。

## [Unreleased]

（現時点で予定されている変更なし)

## [1.0.0] - 2026-07-11

初回リリース。データ取得方法を抽象化した `DataSource` アーキテクチャへの刷新を含む。

### Added

- **データ取得の抽象化**: `interfaces/schema.py` に canonical schema (`Listing`, `SCHEMA_VERSION = "1.0"`) を定義。
  取得方法によらず統一されたスキーマでデータを扱えるようにした。
  - `interfaces.schema.validate_listing()`: 必須キー・型・欠損値ルールを検証し、
    `ValidationError(field, message)` の形で分かりやすいエラー内容を返す
  - 欠損値ルールを統一: スカラーは `None`、複数値(`tags`/`materials`/`images`)は空配列、
    元データは常に `raw` に保持
- **`DataSource` (ABC, `interfaces/datasource.py`)** と4つの実装:
  - `EtsyAPIDataSource`: 既存 `etsy_api.EtsyAPIClient` をラップ
  - `CSVDataSource`: canonical schema準拠CSV / 任意列名+`--mapping`辞書の2モードに対応
  - `HTMLDataSource`: **保存済みHTMLファイルのみ**を対象(ライブクロール等の自動アクセスは行わない)。
    実解析はサイト別パーサー(`interfaces/html_parsers/`, 既定は `EtsyHTMLParser`)に委譲する構造
  - `JSONDataSource`: JSON配列(または `results_key` でラップされた配下)から読み込み
- **`adapter.py`**: canonical schema (`Listing`) を既存 `analyzer.EtsyAnalyzer` の入力形式へ変換する
  橋渡し層。`analyzer.py` と `interfaces/` は互いに依存しない構成を維持
- **`main.py` の新オプション**: `--source {api,csv,html,json}` / `--input PATH` / `--mapping PATH`
  - sourceごとに必須の引数(`api`:`--keyword`、`csv`/`html`/`json`:`--input`)を検証し、
    不正な組み合わせは明確なエラーメッセージで停止
  - 取得したデータをcanonical schemaで検証し、違反があれば `ValidationError` の内容を表示して停止
    (不正なデータのままCSV/Excel等は生成しない)
- **テスト追加**(166件、うち新規109件):
  `tests/test_datasource_schema.py` / `_csv.py` / `_json.py` / `_html.py` / `_etsy_api.py` /
  `_contract.py`(4実装共通の契約テスト)、`tests/test_adapter.py`、
  `tests/test_main_integration.py`(CLI統合テスト)
- README.mdを新しいDataSource対応CLI仕様に全面更新

### Changed

- `main.py` のエントリーポイントを、`DataSource` 経由の取得 → canonical schema検証 →
  `adapter.build_analyzer()` → 既存の分析・出力パイプライン、という構成に刷新
  (`--source` 省略時は `api` が既定で、従来の `--keyword` のみのコマンドラインはそのまま動作する)
- `EtsyAPIDataSource` の初期化エラー(APIキー未設定など)を `DataSourceError` に正規化し、
  取得方法によらず呼び出し側が1種類の例外だけを catch すればよいようにした
- `.gitignore`: `output/` 配下の生成物(`.md`/`.json`/`.txt`を含む全形式)と `.pytest_cache/` を除外対象に追加
  (従来は `*.csv`/`*.xlsx` のみが対象で、Markdownレポート等の他形式が漏れていた)

### Not changed

- `analyzer.py` / `reporter.py` / `exporter.py` / `prompt_builder.py` の分析ロジック・
  スコア計算(`score`)の仕様は変更していない
- Etsyサイトへの自動クロール(Playwright等によるライブアクセス)は実装していない。
  検討したが、Etsyの `robots.txt` が検索結果ページのクロールを明示的に禁止していることを
  確認し、本リリースのスコープからは除外した

### Known limitations

- `--source api` は有効な `ETSY_API_KEY` が必要(未設定・無効な場合は `DataSourceError`)
- Etsy Open API経由では販売数・競合ショップのレビュー数/星評価は取得できない
  (公式APIの制約。詳細はREADME「Etsy APIの制約について」を参照)
- `score`(人気度スコア)は公開データからの推定値であり、実際の販売数・レビュー評価ではない
- `EtsyHTMLParser` はJSON-LD構造化データの解析のみに対応し、CSSセレクタによる
  フォールバック解析は未実装(実HTMLサンプルでの検証が別途必要なため)
- lint/formatツール(black/flake8/ruff/mypy等)は未導入
