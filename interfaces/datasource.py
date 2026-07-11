"""
interfaces/datasource.py
--------------------------
取得方法(Etsy API / CSV / 保存済みHTML / JSON)に依存しない
データ取得インターフェース DataSource と、その4実装。

すべての実装は interfaces.schema.CANONICAL_FIELDS で定義された
canonical schema準拠のdictのリストを返す。呼び出し側(将来のmain.py等)は
どの実装を使っていてもEtsyAnalyzer(raw_listings, keyword=...)へそのまま
渡せる。

analyzer.py はimportしない(依存しない)。canonical schemaは
interfaces.schema に独立して定義されており、analyzer.normalize_listing()
が期待する形にこのモジュール側で合わせている。
"""

from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from .html_parsers import EtsyHTMLParser, HTMLListingParser
from .schema import CANONICAL_FIELDS, SCHEMA_VERSION, Listing, empty_listing


class DataSourceError(Exception):
    """全DataSource実装が共通して投げる例外。

    呼び出し側は実装(API/CSV/HTML/JSON)を問わず、この1種類だけを
    catchすればよい設計にするための正規化用の例外クラス。
    """


class DataSource(ABC):
    """
    データ取得方法(Etsy API / CSV / 保存済みHTML / JSON)を抽象化する
    共通インターフェース(ABC)。

    全ての具象実装は fetch_listings() で必ず List[Listing]
    (interfaces.schema.CANONICAL_FIELDS 準拠のcanonical schema)を
    返さなければならない。
    """

    #: この実装が準拠するcanonical schemaのバージョン。
    #: 既定ではinterfaces.schema.SCHEMA_VERSIONを参照する。
    #: 将来schemaを破壊的変更する際、特定の実装だけ旧バージョンに
    #: 留まる場合はサブクラス側でoverrideする想定。
    schema_version: str = SCHEMA_VERSION

    @abstractmethod
    def fetch_listings(
        self, keyword: str, max_results: int = 50, **kwargs: Any
    ) -> List[Listing]:
        """
        canonical schema (interfaces.schema.CANONICAL_FIELDS, version
        self.schema_version) 準拠の Listing のリストを返す。

        Args:
            keyword: 検索キーワード。ファイルベースの実装(CSV/HTML/JSON)は
                無視するか、対応する列/フィールドがあれば絞り込みに使う。
            max_results: 返すlistingの最大件数。
            **kwargs: 実装固有の追加オプション。

        Raises:
            DataSourceError: 取得・変換に失敗した場合。実装ごとの例外は
                すべてこの型に正規化してraiseすること。
        """
        raise NotImplementedError

    def __enter__(self) -> "DataSource":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """リソース解放が必要な実装だけoverrideする。既定は何もしない。"""
        return None


class EtsyAPIDataSource(DataSource):
    """
    Etsy Open API v3 から取得する実装。

    etsy_api.EtsyAPIClient をラップし、そのレスポンス(既にcanonical
    schemaとほぼ同じ形)をcanonical schemaへ詰め替えて返す。

    テスト時はclient引数にモック/フェイクのクライアントを注入できる
    (search_active_listings(keyword, max_results, sort_on) と
    enrich_listings(listings) を実装したオブジェクトであればよい)。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        if client is not None:
            self._client = client
            return

        # etsy_apiは実運用時のみ必要なため遅延import
        # (このモジュール自体はrequests/環境変数に依存させない)
        try:
            from etsy_api import EtsyAPIClient

            self._client = EtsyAPIClient(api_key=api_key, access_token=access_token)
        except Exception as exc:  # etsy_api.EtsyAPIError(APIキー未設定等)を正規化する
            raise DataSourceError(f"Etsy APIクライアントの初期化に失敗しました: {exc}") from exc

    def fetch_listings(
        self,
        keyword: str,
        max_results: int = 50,
        sort_on: str = "score",
        skip_enrich: bool = False,
        **kwargs: Any,
    ) -> List[Listing]:
        try:
            raw_listings = self._client.search_active_listings(
                keyword=keyword, max_results=max_results, sort_on=sort_on
            )
            if not skip_enrich and hasattr(self._client, "enrich_listings"):
                self._client.enrich_listings(raw_listings)
        except DataSourceError:
            raise
        except Exception as exc:  # etsy_api.EtsyAPIError等を正規化する
            raise DataSourceError(f"Etsy APIからの取得に失敗しました: {exc}") from exc

        return [self._to_canonical(item) for item in raw_listings]

    @staticmethod
    def _to_canonical(item: Dict[str, Any]) -> Listing:
        listing = empty_listing(raw=item)
        for field in CANONICAL_FIELDS:
            if field == "raw":
                continue
            if field in item:
                listing[field] = item[field]
        listing["tags"] = list(item.get("tags") or [])
        listing["materials"] = list(item.get("materials") or [])
        listing["images"] = list(item.get("images") or [])
        return listing

    def close(self) -> None:
        session = getattr(self._client, "session", None)
        if session is not None and hasattr(session, "close"):
            session.close()


class CSVDataSource(DataSource):
    """
    CSVファイルから読み込む実装。2つのモードに対応する。

    1. canonical schema準拠CSV (column_mapping省略時):
       列名がcanonical schemaのフィールド名(raw以外)と一致している想定。
       tags/materials/images/price のようなlist・dict型フィールドは、
       セル内にJSON文字列として格納されている想定(例: '["a", "b"]')。

    2. 任意列名 + column_mapping:
       {canonical_field_name: csv_column_name} の辞書を渡すと、
       その列名からcanonical fieldへ変換する。マッピングされなかった
       canonical fieldは欠損値ルールに従いNone/[]になる。
    """

    def __init__(
        self,
        path: str,
        column_mapping: Optional[Dict[str, str]] = None,
        encoding: str = "utf-8-sig",
    ) -> None:
        self.path = path
        self.column_mapping = column_mapping
        self.encoding = encoding

    def fetch_listings(
        self, keyword: str = "", max_results: int = 50, **kwargs: Any
    ) -> List[Listing]:
        try:
            with open(self.path, newline="", encoding=self.encoding) as f:
                rows = list(csv.DictReader(f))
        except OSError as exc:
            raise DataSourceError(f"CSVファイルの読み込みに失敗しました: {exc}") from exc

        return [self._row_to_canonical(row) for row in rows[:max_results]]

    def _row_to_canonical(self, row: Dict[str, Optional[str]]) -> Listing:
        listing = empty_listing(raw=dict(row))
        mapping = self.column_mapping or {
            name: name for name in CANONICAL_FIELDS if name != "raw"
        }

        for field, column in mapping.items():
            if field == "raw" or field not in CANONICAL_FIELDS:
                continue
            listing[field] = self._coerce(field, row.get(column))

        return listing

    @staticmethod
    def _coerce(field: str, raw_value: Optional[str]) -> Any:
        spec = CANONICAL_FIELDS[field]

        if raw_value is None or raw_value == "":
            return [] if spec.is_list else None

        if spec.is_list:
            try:
                parsed = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                return []
            return parsed if isinstance(parsed, list) else []

        if spec.types == (dict,):
            try:
                parsed = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                return None
            return parsed if isinstance(parsed, dict) else None

        if spec.types == (bool,):
            return str(raw_value).strip().lower() in ("true", "1", "yes")

        if spec.types == (int,):
            try:
                return int(float(raw_value))
            except (TypeError, ValueError):
                return None

        if int in spec.types and str in spec.types:  # shop_id等
            try:
                return int(float(raw_value))
            except (TypeError, ValueError):
                return raw_value

        return raw_value


class JSONDataSource(DataSource):
    """
    JSONファイルから読み込む実装。

    JSON側はcanonical schemaのフィールド名をそのまま使う想定
    (list/dict型もJSONがネイティブに表現できるため、CSVと違って
    追加のエンコード/デコードは不要)。

    トップレベルが配列でなく `{"results": [...]}` のようにラップ
    されている場合は results_key で配下のキーを指定する。
    """

    def __init__(
        self, path: str, results_key: Optional[str] = None, encoding: str = "utf-8"
    ) -> None:
        self.path = path
        self.results_key = results_key
        self.encoding = encoding

    def fetch_listings(
        self, keyword: str = "", max_results: int = 50, **kwargs: Any
    ) -> List[Listing]:
        try:
            with open(self.path, encoding=self.encoding) as f:
                data = json.load(f)
        except OSError as exc:
            raise DataSourceError(f"JSONファイルの読み込みに失敗しました: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DataSourceError(f"JSONの解析に失敗しました: {exc}") from exc

        if self.results_key is not None:
            if not isinstance(data, dict):
                raise DataSourceError(
                    f"results_key='{self.results_key}' 指定時、JSONのトップレベルは"
                    "オブジェクトである必要があります。"
                )
            data = data.get(self.results_key, [])

        if not isinstance(data, list):
            raise DataSourceError(
                "JSONのトップレベル(またはresults_key配下)はリストである必要があります。"
            )

        return [self._item_to_canonical(item) for item in data[:max_results]]

    @staticmethod
    def _item_to_canonical(item: Dict[str, Any]) -> Listing:
        listing = empty_listing(raw=item)
        for field in CANONICAL_FIELDS:
            if field == "raw":
                continue
            if field in item:
                listing[field] = item[field]
        return listing


class HTMLDataSource(DataSource):
    """
    保存済みHTMLファイルから読み込む実装。ライブクロール/HTTP取得は
    一切行わない(取得手段は呼び出し側の責任)。

    実際のDOM/構造化データの解析はサイト別パーサー(HTMLListingParser)に
    委譲する。デフォルトはEtsy用パーサー(EtsyHTMLParser)。
    """

    def __init__(
        self,
        paths: Union[str, List[str]],
        parser: Optional[HTMLListingParser] = None,
    ) -> None:
        self.paths: List[str] = [paths] if isinstance(paths, str) else list(paths)
        self.parser: HTMLListingParser = parser or EtsyHTMLParser()

    def fetch_listings(
        self, keyword: str = "", max_results: int = 50, **kwargs: Any
    ) -> List[Listing]:
        listings: List[Listing] = []

        for path in self.paths:
            try:
                with open(path, encoding="utf-8") as f:
                    html = f.read()
            except OSError as exc:
                raise DataSourceError(
                    f"HTMLファイルの読み込みに失敗しました ({path}): {exc}"
                ) from exc

            try:
                parsed_items = self.parser.parse(html)
            except Exception as exc:  # パーサー内部の想定外エラーも正規化する
                raise DataSourceError(f"HTML解析に失敗しました ({path}): {exc}") from exc

            for item in parsed_items:
                listings.append(self._to_canonical(item))
                if len(listings) >= max_results:
                    return listings

        return listings

    @staticmethod
    def _to_canonical(item: Dict[str, Any]) -> Listing:
        listing = empty_listing(raw=item.get("raw", {}))
        for field in CANONICAL_FIELDS:
            if field == "raw":
                continue
            if field in item:
                listing[field] = item[field]
        return listing
