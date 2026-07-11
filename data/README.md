# data/etsy_sample.csv

Etsy商品分析ツール(`--source csv`)向けの、canonical schema準拠CSVテンプレートです。
ヘッダー行と、フォーマット確認用の入力例1行のみを収録しています
(実在・架空を問わず、商品データそのものは含みません)。

## 使い方

```bash
python main.py --source csv --input data/etsy_sample.csv --keyword "検索キーワード" --report --json --prompt
```

入力例の行を削除し、実際のEtsy商品データを1行1商品としてこの形式で追記してください。
1ファイルあたり `--max-results` で指定した件数まで読み込まれます(目安として20件程度を想定)。

## 列の説明

`interfaces/schema.py` の canonical schema (`SCHEMA_VERSION = "1.0"`) にある
フィールドのうち、`raw`(元データ保持用の内部フィールド)を除く20列です。
`raw` 列はCSVには含めません。CSVDataSourceが各行全体を自動的に `raw` として保持します。

| 列名 | 必須 | 型 | 内容 | 入力形式の注意 |
|---|---|---|---|---|
| `listing_id` | ✅必須 | int | 商品ID | 数値のみ |
| `title` | | str | 商品タイトル | プレーンテキスト |
| `url` | | str | 商品ページURL | そのまま文字列 |
| `price` | | dict | `{"amount": int, "divisor": int, "currency_code": str}` | セル内にJSON文字列で記述(例: `{"amount": 1500, "divisor": 100, "currency_code": "USD"}`)。実価格 = `amount / divisor` |
| `quantity` | | int | 在庫数 | 数値のみ |
| `tags` | | list[str] | タグ一覧 | セル内にJSON配列文字列(例: `["tag1", "tag2"]`)。空の場合は列を空欄にする |
| `materials` | | list[str] | 素材一覧 | `tags` と同じくJSON配列文字列 |
| `shop_id` | | int または str | ショップID | 数値または文字列 |
| `shop_name` | | str | ショップ名 | プレーンテキスト |
| `shop_url` | | str | ショップURL | そのまま文字列 |
| `num_favorers` | | int | お気に入り数 | 数値のみ |
| `featured_rank` | | int | 検索結果内の掲載順位 | 数値のみ |
| `when_made` | | str | 製造時期 (Etsy APIの語彙。例: `made_to_order`, `2020_2024` 等) | プレーンテキスト |
| `who_made` | | str | 製造者区分 (Etsy APIの語彙。例: `i_did`, `someone_else`, `collective`) | プレーンテキスト |
| `is_customizable` | | bool | カスタマイズ可否 | `true`/`false`/`1`/`0`/`yes` のいずれか |
| `taxonomy_id` | | int | カテゴリID | 数値のみ |
| `creation_timestamp` | | int | 作成日時 (unix time, 秒) | 数値のみ |
| `last_modified_timestamp` | | int | 更新日時 (unix time, 秒) | 数値のみ |
| `description` | | str | 商品説明文 | プレーンテキスト(改行はセル内改行として問題なし) |
| `images` | | list[dict] | 画像情報のリスト。各要素は `{"rank": int, "url_fullxfull": str, "hex_code": str, "brightness": int}` 等 | セル内にJSON配列文字列 |

**欠損値のルール**

- 空欄にすると、スカラー値は `None`、`tags`/`materials`/`images` は空配列 `[]` として扱われます。
- `listing_id` のみ必須です。空欄のまま実行すると `interfaces.schema.validate_listing()` の検証でエラーになり、
  `main.py` が処理を停止します。

## 参考

- 列名・型・欠損値ルールの正本は `interfaces/schema.py` です。本ファイルとズレが生じた場合はそちらを優先してください。
- CSVの読み込みロジックは `interfaces/datasource.py` の `CSVDataSource` です。
- 任意の列名のCSVを使いたい場合は、本テンプレートを使わず `--mapping` オプションで
  `{"canonical_field": "csv列名"}` 形式のマッピングファイルを指定する方法もあります
  (詳細はプロジェクトルートの `README.md` を参照)。
