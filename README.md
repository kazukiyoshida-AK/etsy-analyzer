# Etsy分析ツール

Etsyの商品データを取得し、CSV / Excel / Markdownレポート / JSON / AI分析用プロンプトに
まとめて出力する競合分析ツールです。

データの取得方法は **Etsy Open API / CSV / 保存済みHTML / JSON** の4種類から選べます
(`--source` オプション)。どの取得方法を使っても、同じ分析・スコアリング・出力ロジック
(`analyzer.py` / `reporter.py` / `exporter.py` / `prompt_builder.py`)がそのまま使われます。

---

## 📌 まずはこれだけ読めばOK

### ✅ 現在できること

- `--source {api,csv,html,json}` で商品データの取得方法を選択(後述)
- 取得したデータを人気度スコア(0〜100)付きでCSV / Excelに保存
- 分析結果からMarkdown市場レポート(`--report`)、AI分析向けJSON(`--json`)、
  ChatGPT/Claude/Geminiに貼れる分析プロンプト(`--prompt`)を生成

### ❌ 現在できないこと(共通の制約)

- **販売数(何個売れたか)は取得できません。** Etsy Open API v3にそのフィールドが存在しないためです。
- **競合ショップのレビュー数・星評価は取得できません。** レビュー取得系エンドポイントはOAuth必須で、
  実質的にショップ所有者本人しかアクセスできず、競合分析には使えないためです(詳細は
  [Etsy APIの制約について](#etsy-apiの制約について-source-api) を参照)。
- 上記のため、本ツールの **`score`(人気度スコア)はあくまで公開データからの"人気度の推定値"であり、
  実際の販売数やレビュー評価を示すものではありません。**

### 🚀 最初におすすめの実行コマンド(Etsy Open APIを使う場合)

```bash
python main.py --keyword "Japanese wall art" --max-results 50 --report --json --prompt
```

`--source` を省略すると `api`(Etsy Open API)が使われます。`ETSY_API_KEY` が必要です
(詳細は [セットアップ](#セットアップ) を参照)。

### `--report` / `--json` / `--prompt` の使い分け

| オプション | 用途 | こんな人におすすめ |
|---|---|---|
| `--report` | 人間が読むMarkdownレポート(.md)を生成 | まず自分の目でざっと市場感を掴みたい |
| `--json` | AI分析用に構造化されたJSON(.json)を生成 | 自作のAI連携ツール・スクリプトに読み込ませたい |
| `--prompt` | ChatGPT/Claude/Geminiにそのまま貼れるプロンプト(.txt)を生成 | チャットAIにその場で市場分析・商品企画を相談したい |

3つは併用可能で、迷ったら上記のおすすめコマンドのように全部つけて実行し、
用途に応じて出力されたファイルを使い分けるのが手軽です。

---

## アーキテクチャ

商品データの「取得」と「分析・出力」を分離した構成になっています。

```
DataSource(ABC)                     analyzer.py / reporter.py /
  ├─ EtsyAPIDataSource   ─┐          exporter.py / prompt_builder.py
  ├─ CSVDataSource        │              ↑
  ├─ HTMLDataSource       ├─ canonical  │ (raw_listings形式のdict)
  └─ JSONDataSource      ─┘  schema     │
        │ fetch_listings()   (Listing) │
        └──────────────→ adapter.py ───┘
                       (build_analyzer)
```

- **canonical schema (`interfaces/schema.py`)**: 取得方法によらず統一されたスキーマ。
  `DataSource.fetch_listings()` は必ずこのスキーマ準拠の `List[Listing]` を返す
  (`Listing` は `TypedDict`。実体は通常のdict)。バージョンは `SCHEMA_VERSION = "1.0"`。
- **`DataSource` (ABC, `interfaces/datasource.py`)**: 取得方法を抽象化する共通インターフェース。
  直接インスタンス化はできない(`fetch_listings()` を実装したサブクラスのみ利用可能)。
  - **`EtsyAPIDataSource`**: Etsy Open API v3(`etsy_api.py`)をラップする実装
  - **`CSVDataSource`**: CSVファイルから読み込む実装(2モード。後述)
  - **`HTMLDataSource`**: 保存済みHTMLファイルから読み込む実装(サイト別パーサーに解析を委譲)
  - **`JSONDataSource`**: JSONファイルから読み込む実装
- **`adapter.py`**: canonical schema (`Listing`) を、既存の `analyzer.EtsyAnalyzer` が期待する
  生データの形へ変換する橋渡し層。`analyzer.py` は `interfaces/` を一切importせず、
  `interfaces/` も `analyzer.py` を一切importしません。両方を知っているのは `adapter.py` だけです。
  `main.py` は `adapter.build_analyzer(listings, keyword=...)` 経由でのみ `EtsyAnalyzer` を構築します。

この分離により、`analyzer.py` 以降(スコア計算・CSV/Excel保存・Markdownレポート・AI向けJSON・
プロンプト生成)は取得方法を意識せず、共通のロジックとして動作します。

## フォルダ構成

```
etsy-analyzer/
├── main.py                     # CLIエントリーポイント
├── adapter.py                  # canonical schema -> EtsyAnalyzer の変換層
├── analyzer.py                 # データ整形・分析・スコアリング・保存担当
├── reporter.py                 # Markdown市場レポート生成
├── exporter.py                 # AI分析向けJSON生成
├── prompt_builder.py           # AI分析用プロンプト(.txt)生成
├── etsy_api.py                 # Etsy Open API v3 通信担当(EtsyAPIDataSourceが利用)
├── interfaces/
│   ├── schema.py                # canonical schema定義 (Listing, validate_listing, SCHEMA_VERSION)
│   ├── datasource.py            # DataSource(ABC) + 4実装 + DataSourceError
│   └── html_parsers/
│       ├── base.py               # HTMLListingParser(ABC)
│       └── etsy.py                # EtsyHTMLParser (JSON-LD構造化データから抽出)
├── requirements.txt            # 依存パッケージ
├── requirements-dev.txt        # テスト用依存パッケージ(pytest)
├── .env.example                 # 環境変数サンプル(apiソース使用時のみ必要)
├── .gitignore
├── README.md
├── tests/                       # pytestユニットテスト・統合テスト
│   ├── test_analyzer.py / test_reporter.py / test_exporter.py / test_prompt_builder.py
│   ├── test_etsy_api.py
│   ├── test_datasource_schema.py / test_datasource_csv.py / test_datasource_json.py /
│   │   test_datasource_html.py / test_datasource_etsy_api.py / test_datasource_contract.py
│   ├── test_adapter.py
│   ├── test_main_integration.py  # main.py全体の統合テスト
│   └── fixtures/                  # CSV/JSON/HTMLサンプル
└── output/                       # CSV / Excel / Markdownレポート / JSON / プロンプトの出力先
```

## セットアップ

### 1. 依存パッケージのインストール

```bash
python -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Etsy APIキーの取得(`--source api` を使う場合のみ必要)

`--source csv` / `--source html` / `--source json` を使う場合、Etsy APIキーは不要です。
`--source api`(デフォルト)を使う場合のみ、以下の準備が必要です。

1. https://www.etsy.com/developers/register にアクセス
2. アプリを登録し、`Keystring` (APIキー) を取得
3. 「アクティブな商品検索」エンドポイントはAPIキーのみで利用可能です

### 3. `.env` ファイルの作成(`--source api` を使う場合のみ)

`.env.example` をコピーして `.env` を作成し、取得したAPIキーを設定してください。

```bash
cp .env.example .env
```

```
ETSY_API_KEY=あなたのAPIキー
```

---

## 使い方

### CLIオプション一覧

| オプション | 説明 | デフォルト |
|---|---|---|
| `--source` | データ取得方法。`api` / `csv` / `html` / `json` から選択 | `api` |
| `--input PATH` | csv/html/jsonソース使用時の入力ファイルパス | なし |
| `--mapping PATH` | csvソース使用時、任意列名→canonical schemaの対応を書いたJSONファイルのパス(任意) | なし |
| `--keyword` `-k` | 検索キーワード。省略時は対話入力(全source共通) | 対話入力 |
| `--max-results` `-n` | 取得する商品件数の上限 | 50 |
| `--sort-on` | 並び替え基準 (`score`/`created`/`price`/`updated`。**apiソースのみ有効**) | `score` |
| `--skip-enrich` | ショップ情報・画像情報の取得をスキップ(**apiソースのみ有効**) | 無効(取得する) |
| `--report` | 分析結果からMarkdown市場レポート(.md)も生成する | 無効 |
| `--json` | 分析結果からAI分析向けJSON(.json)も生成する | 無効 |
| `--prompt` | 分析結果からAI分析用プロンプト(.txt)を生成する | 無効 |

### sourceごとの必須条件

| source | 必須 | 任意 | 備考 |
|---|---|---|---|
| `api` | `--keyword` | `--sort-on` / `--skip-enrich` | `--input` / `--mapping` は指定不可(指定するとエラー) |
| `csv` | `--input` | `--mapping` | `--mapping` 省略時はcanonical schema準拠CSVとして読む |
| `html` | `--input` | — | **保存済みHTMLファイルのみ**対象(後述) |
| `json` | `--input` | — | — |

不正な組み合わせ(例: `--source api` に `--input` を指定、`--source csv` で `--input` 未指定など)は、
実行時に `エラー: ...` という分かりやすいメッセージを出して終了します。

### 実行例

**1. Etsy Open API (`--source api`, デフォルト)**

```bash
python main.py --keyword "Japanese wall art" --max-results 50 --report --json --prompt
```

**2. CSV (`--source csv`)**

```bash
# canonical schema準拠CSV(--mapping省略)
python main.py --source csv --input data/listings.csv --keyword "cat mug" --report

# 任意列名のCSV + マッピングファイル
python main.py --source csv --input data/listings.csv --mapping mapping.json --keyword "cat mug"
```

**3. 保存済みHTML (`--source html`)**

```bash
python main.py --source html --input saved_page.html --keyword "Japanese wall art" --json
```

**4. JSON (`--source json`)**

```bash
python main.py --source json --input data/listings.json --keyword "Japanese wall art" --prompt
```

`--keyword` を省略した場合は、全source共通で対話的にキーワードを聞かれます
(`python main.py` のみで実行した場合も同様)。

---

## canonical schema

`DataSource.fetch_listings()` は、取得方法によらず必ず以下のスキーマ(`interfaces.schema.Listing`,
`SCHEMA_VERSION = "1.0"`)準拠のリストを返します。

| フィールド | 型 | 内容 |
|---|---|---|
| `listing_id` | int (必須) | 商品ID |
| `title` | str \| None | 商品タイトル |
| `url` | str \| None | 商品ページURL |
| `price` | dict \| None | `{"amount": int, "divisor": int, "currency_code": str}` |
| `quantity` | int \| None | 在庫数 |
| `tags` | list[str] | タグ一覧 |
| `materials` | list[str] | 素材一覧 |
| `shop_id` | int \| str \| None | ショップID |
| `shop_name` / `shop_url` | str \| None | ショップ名・URL |
| `num_favorers` | int \| None | お気に入り数 |
| `featured_rank` | int \| None | 検索内の掲載順位 |
| `when_made` / `who_made` | str \| None | 製造時期・製造者区分 |
| `is_customizable` | bool \| None | カスタマイズ可否 |
| `taxonomy_id` | int \| None | カテゴリID |
| `creation_timestamp` / `last_modified_timestamp` | int \| None | 作成/更新日時(unix time) |
| `description` | str \| None | 商品説明文 |
| `images` | list[dict] | 画像情報(`rank`, `url_fullxfull`等, `hex_code`, `brightness`) |
| `raw` | dict (必須) | 変換元の生データ(取得方法によらず必ず保持) |

**欠損値ルール**

- 取得できなかったスカラー値は `None`
- 取得できなかった複数値(`tags` / `materials` / `images`)は空配列 `[]`
- 元データは必ず `raw` に保持する(取得方法を問わない共通ルール)

`interfaces.schema.validate_listing(listing)` でこのルールへの適合を検証でき、
違反があれば `ValidationError(field, message)` のリスト(空なら適合)を返します。
`main.py` は取得直後に全listingへこの検証をかけ、違反があれば内容を表示して処理を止めます
(不正なデータのままCSV/Excel等は生成しません)。

## CSVDataSourceの2モード

`--mapping` の指定有無で、CSVの読み方が変わります。

1. **canonical schema準拠CSV(`--mapping` 省略時)**: 列名がcanonical schemaのフィールド名
   (`listing_id`, `title`, `price`, ...)と一致している前提で読み込みます。
   `tags` / `materials` / `images` / `price` のようなlist・dict型フィールドは、
   セル内にJSON文字列として格納します(例: `["a", "b"]`)。
2. **任意列名 + `--mapping`**: `{"canonical_field": "csv列名", ...}` 形式のJSONファイルを
   `--mapping` に指定すると、その対応でCSVの列をcanonical schemaへマッピングします。
   マッピングされなかったフィールドは欠損値ルール通り `None` / `[]` になります。

```json
{
  "listing_id": "ID",
  "title": "ProductName",
  "url": "Link"
}
```

## HTMLDataSourceの制約

- **保存済みHTMLファイルのみ**を対象とします。ネットワークアクセス・ライブクロール・
  自動アクセスは一切行いません(HTMLの取得手段は呼び出し側の責任です)。
- 実際の解析はサイト別パーサー(`interfaces/html_parsers/`)に委譲する構造になっており、
  既定は Etsy 用パーサー `EtsyHTMLParser` です。
- `EtsyHTMLParser` は、商品ページに埋め込まれた schema.org の `Product` 構造化データ
  (`<script type="application/ld+json">`)を一次情報源として解析します。
  CSSセレクタによるフォールバック解析は、実HTMLサンプルでの検証が別途必要なため
  未実装です(構造化データが見つからない場合は空リストを返します)。

---

## 出力

`output/` フォルダに、以下のファイルが `キーワード_日時` の形式で保存されます。
商品一覧は **人気度スコア(score)の降順** で並びます。

- `キーワード_日時.csv` : 商品一覧 (CSV)
- `キーワード_日時.xlsx` : 商品一覧 + 分析サマリー (Excel)
  - `listings` シート: 商品一覧(ショップ名・画像URL・スコアなどを含む)
  - `summary` シート : 価格帯などの基本統計
  - `top_tags` シート: 頻出タグランキング
- `キーワード_日時_report.md` : **(`--report` 指定時のみ)** Markdown市場レポート
- `キーワード_日時.json` : **(`--json` 指定時のみ)** AI分析向けJSON
- `キーワード_日時_prompt.txt` : **(`--prompt` 指定時のみ)** AI分析用プロンプト

## 現在の分析機能

### 基本統計
- 取得件数 / 価格の最小・最大・平均・中央値 / ユニークショップ数 / 頻出タグ TOP20

### 商品ごとの付加情報(`--source api` かつ `--skip-enrich` 未指定の場合)

`EtsyAPIDataSource` は、`--skip-enrich` を指定しない場合、各商品に対して以下を追加取得します
(csv/html/jsonソースでは、そのソースが `raw` 以外のcanonical schemaフィールドとして
提供した範囲の情報のみが使われます)。

| 項目 | 取得元 | 備考 |
|---|---|---|
| `shop_name` / `shop_url` | `GET /shops/{shop_id}` | 同じshop_idはキャッシュされ、API呼び出しは1回のみ |
| `primary_image_url` / `image_count` | `GET /listings/{listing_id}/images` | 代表画像(rank最小)のURL。listing_idごとにキャッシュ |
| `image_color_hex` / `image_brightness` | 同上 | 代表画像の色情報 |

### 人気度スコア (score)

`num_favorers` / `featured_rank` / `price` / `tag_count` / `image_count` /
`last_modified_timestamp`(更新の新しさ) / キーワード一致(タイトル・タグ・説明文)
を組み合わせて 0〜100 のスコアを算出し、`listings` シートに降順で並べています。

計算方法の詳細やそれぞれの重みは `analyzer.py` の `EtsyAnalyzer.score_listing()` の
docstring・コメントに記載しています。重みや「価格は安いほど高評価とする」といった
設計判断は分析目的に応じて調整してください。

## Markdown市場レポート

`--report` オプションを付けて実行すると、分析結果から市場レポートをMarkdown(.md)ファイルとして
`output/` に保存します。sourceを問わず同じレポートロジック(`reporter.py`)が使われます。

```bash
python main.py --keyword "Japanese wall art" --max-results 50 --report
```

レポートには以下の内容が含まれます。

- 検索キーワード / 取得件数
- 価格帯 / 平均価格 / 中央値価格
- ユニークショップ数
- 人気タグ TOP20
- スコア上位10件(人気度推定)
- 価格帯別の商品数
- お気に入り数 TOP10
- 画像枚数の傾向(平均・中央値・0枚の割合など)
- 参入判断メモ(競合の分散度・価格帯の広がり・画像投資水準などから自動生成する簡易コメント)

⚠️ **レポート冒頭と「参入判断メモ」の両方に、
「このレポートは公開データに基づく人気度の推定値であり、実際の販売数を
示すものではない」という注記を明記しています。**

レポート生成ロジックは `reporter.py` にまとまっており、
`EtsyAnalyzer.df`(スコア計算済みのDataFrame)を渡すだけで
`generate_market_report()` / `save_market_report()` から呼び出せます。

## AI分析向けJSON出力

`--json` オプションを付けて実行すると、分析結果をAI(LLM)に渡しやすい
JSON形式で `output/` に保存します。

```bash
python main.py --keyword "Japanese wall art" --max-results 50 --json
```

JSONのトップレベル構造:

| キー | 内容 |
|---|---|
| `keyword` | 検索キーワード |
| `generated_at` | 生成日時 (ISO8601) |
| `disclaimer` | ⚠️ 「販売数ではなく公開データに基づく人気度推定である」旨の注記(下記参照) |
| `total_count` | 取得件数 |
| `price_summary` | 価格の min/max/mean/median/currency_code |
| `top_tags` | 人気タグ TOP20 (`tag`, `count`) |
| `top_scored_listings` | スコア上位10件 |
| `top_favorited_listings` | お気に入り数上位10件 |
| `shop_summary` | ユニークショップ数、出品数の多いショップ TOP10(今回の検索結果内での集中度) |
| `image_summary` | 画像枚数の平均・中央値・0枚/上限枚数の割合など |
| `raw_listings_compact` | AIに渡す前提で絞り込んだ商品一覧(下記参照) |

`raw_listings_compact` の各要素は、AIへの入力トークンを抑えるため
以下のフィールドのみに絞っています。`description` は先頭500文字に切り詰めます。

```
title, price, currency_code, shop_name, num_favorers,
score, tags, description, primary_image_url, url
```

⚠️ **`disclaimer` キーには、
「本JSONのscore・ランキングは公開データから算出した人気度の推定値であり、
実際の販売数やレビュー評価を示すものではない」という注記を必ず含めています。**

レポート生成ロジックは `exporter.py` にまとまっており、
`EtsyAnalyzer.df` を渡すだけで `generate_ai_json()` / `save_ai_json()` から
呼び出せます。

## AI分析用プロンプト生成

`--prompt` オプションを付けて実行すると、分析結果をもとに
**ChatGPT / Claude / Gemini などのチャットAIにそのまま貼り付けられる
市場分析プロンプト(.txt)** を `output/` に生成します。

```bash
python main.py --keyword "Japanese wall art" --max-results 50 --prompt
```

生成されるプロンプトの構成:

1. 「このデータは販売数ではなく、公開データに基づく人気度推定である」という
   重要な前提の明記
2. 検索キーワード・取得件数・価格帯などのデータ概要
3. `exporter.py` と同じ形式のJSONデータ本体(AIが詳細分析できるよう埋め込み)
4. 以下10項目について見出しを立てて分析するよう依頼する指示文
   - 市場全体の要約
   - 売れ筋商品の共通点
   - 人気タグ分析
   - 価格帯分析
   - 競合の強さ
   - 参入余地
   - 狙うべき商品案
   - 避けるべき商品案
   - 画像生成AI向けプロンプト案
   - Etsyタイトル案
   - Etsyタグ案
5. 出力形式の指定(Markdown・見出し単位でまとめる、画像生成AI向けは英語で
   複数案出す、など)

`--json` を指定していなくても `--prompt` 単体で動作します
(内部で `exporter.generate_ai_json()` を呼び出してプロンプトに埋め込みます)。

⚠️ プロンプト自体にも「人気度スコアは公開データからの推定値であり、実際の
売上を保証するものではない」という前提を明記しています。

---

## Etsy APIの制約について (`--source api`)

`--source api` を使う場合、以下の制約があります(csv/html/jsonソースでは
そもそもEtsy Open APIを使わないため関係ありません)。

- **有効なAPIキー(`ETSY_API_KEY`)が設定されている場合のみ利用可能です。** 未設定・無効な場合は
  `DataSourceError` としてエラーメッセージを表示して終了します。
- **販売数(何個売れたか)は公式APIに存在しません。**
  v2時代にあった `num_sold` 相当のフィールドはv3のShopListing/Shopリソースに
  存在せず、取得手段がありません。
- **競合ショップのレビュー数・星評価は取得できません。**
  レビュー取得エンドポイント(`getReviewsByListing` / `getReviewsByShop`)は
  OAuth認証が必須で、実質的に「そのショップの所有者本人が許可したアクセストークン」
  でなければ取得できません。他人のショップ(競合)のレビューを取得する用途では
  使えないため、本ツールでは実装していません(`EtsyAPIClient.get_listing_reviews`
  は`NotImplementedError`を返します)。
- **ショップ単位の平均評価・レビュー数もShopリソースにありません。**
- **`views`(閲覧数)も競合分析には使えません。**
  `getListing`のレスポンスに含まれますが、ショップ所有者本人のOAuthトークンで
  ないと取得できない想定です。
- **検索エンドポイント(`listings/active`)には `includes` パラメータがありません。**
  画像・ショップ情報などの関連データを一括取得できないため、`EtsyAPIDataSource` は
  商品ごとに `getListingImages` / `getShop` を追加で呼び出しています
  (`shop_id` / `listing_id` ごとにキャッシュ済み)。

### ⚠️ 「人気度スコア」は推定値であり、実際の販売数・評価ではありません

上記の制約により、本ツールが算出する `score`(人気度スコア)は
**お気に入り数・検索順位・鮮度・キーワード一致度など、公開データから作った
「相対的な人気度の推定値」** です。csv/html/jsonソースを使う場合も、元データに
販売数・レビュー情報が含まれない限り同様です。

- 実際に何個売れたか(販売数)を示すものではありません。
- 星評価・レビュー内容を反映したものでもありません。
- あくまで「今回取得した商品群の中での相対比較」であり、絶対的な指標ではありません。

分析結果を解釈・利用する際は、この点を必ず踏まえてください。

## 今後の拡張予定

- `EtsyHTMLParser` へのCSSセレクタベースのフォールバック解析(実HTMLサンプルでの検証が必要)
- 画像そのものを解析する詳細な画像分析(構図・被写体など。色情報・枚数は実装済み)
- `analyzer.py` の以下のプレースホルダーメソッドの実装

  | 機能 | 該当メソッド | 概要 |
  |---|---|---|
  | 画像の詳細分析 | `EtsyAnalyzer.analyze_images` | 画像そのものを解析する構図・被写体分析など |
  | AI分析 | `EtsyAnalyzer.analyze_with_ai` | LLMを使ったタイトル/タグ/売れ筋傾向の分析 |

## テストの実行方法

`tests/` フォルダにpytestベースのユニットテスト・統合テストを用意しています。
実際のEtsy APIやネットワークには一切接続せず、`EtsyAPIClient._get` やフェイクの
`DataSource` 実装に差し替えてテストします。

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
```

最新実行時点で166件成功しています(件数はテスト追加により今後増える可能性があるため、
固定値としてではなく実行結果を都度確認してください)。

主なテスト内容:

| ファイル | 検証内容 |
|---|---|
| `tests/test_etsy_api.py` | 検索のページング、`get_shop`/`get_listing_images`のキャッシュ、`enrich_listings`でのAPIコール重複排除など |
| `tests/test_analyzer.py` | `normalize_listing`の各フィールド抽出、`basic_stats`、`score`が0〜100に収まることなど |
| `tests/test_reporter.py` / `test_exporter.py` / `test_prompt_builder.py` | 各出力の必須項目・注記の有無・ファイル保存の正しさ |
| `tests/test_datasource_schema.py` | canonical schemaの定義・`empty_listing`・`validate_listing`のエラー内容 |
| `tests/test_datasource_csv.py` / `_json.py` / `_html.py` / `_etsy_api.py` | 各`DataSource`実装の変換ロジック |
| `tests/test_datasource_contract.py` | 全`DataSource`実装が共通して満たすべき契約(必須キー・型・欠損値ルール)の検証 |
| `tests/test_adapter.py` | canonical schema ↔ `analyzer.normalize_listing()` のフィールド対応が崩れていないことの検証 |
| `tests/test_main_integration.py` | `main.py`をCLI引数から実行するエンドツーエンドの統合テスト(csv/html/json/apiの各source、異常系) |

## 注意事項

- `--source api` はEtsy APIのレート制限にご注意ください(429エラー時は自動でリトライします)。
  `--skip-enrich` を使わない場合、商品件数分だけ画像取得APIが呼ばれるため、
  `--max-results` を大きくするとAPIコール数・実行時間が増加します。
- `--source csv` / `html` / `json` はローカルファイルの読み込みのみで、ネットワークアクセスは
  一切行いません。
- `.env` ファイルはAPIキーを含むため、Gitにコミットしないでください(`.gitignore`済み)。
