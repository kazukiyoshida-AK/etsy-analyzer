"""
etsy_api.py
-----------
Etsy Open API v3 との通信を担当するモジュール。

Phase1: キーワードでアクティブな商品(listing)を検索する機能
Phase2: 商品画像(get_listing_images) / ショップ情報(get_shop) の取得と、
        それらをキャッシュしつつlisting一覧に付与するenrich_listings機能

なお、レビュー数・星評価・販売数については、
  - レビュー取得系エンドポイント(getReviewsByListing/getReviewsByShop)はOAuth必須で、
    実質的にショップ所有者本人のトークンでしかアクセスできない
  - 販売数(件数)を返すフィールドはv3のShopListing/Shopリソースに存在しない
  - ショップ単位の平均評価・レビュー数もShopリソースに存在しない
という公式APIの制約があり、競合分析用途には使えないため、
今回のスコープでは意図的に実装しない(get_listing_reviewsは未実装のまま残す)。

参考: https://developers.etsy.com/documentation/reference/
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests


class EtsyAPIError(Exception):
    """Etsy APIとの通信で発生したエラーを表す例外。"""


class EtsyAPIClient:
    """
    Etsy Open API v3 のシンプルなクライアント。

    現時点ではAPIキー(x-api-key)のみを使った公開エンドポイント
    (アクティブな商品の検索)のみをサポートする。

    将来、OAuthトークンが必要なエンドポイント(レビュー取得など)を
    追加する場合は、access_token を渡して Authorization ヘッダーを
    付与できるように拡張する想定。
    """

    BASE_URL = "https://openapi.etsy.com/v3/application"

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 3,
        retry_wait_seconds: float = 2.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("ETSY_API_KEY") or "").strip() or None
        self.access_token = (access_token or os.getenv("ETSY_ACCESS_TOKEN") or "").strip() or None
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds

        if not self.api_key:
            raise EtsyAPIError(
                "ETSY_API_KEY が設定されていません。.env ファイルを確認してください。"
            )

        self.session = requests.Session()

        # Phase2: 重複APIコールを避けるためのシンプルなインメモリキャッシュ。
        # キーはそれぞれ shop_id / listing_id。
        # 同じキーワードで再検索した場合や、同じショップの商品が複数ヒットした
        # 場合に、同じshop_id/listing_idへのAPIコールを1回にまとめる。
        self._shop_cache: Dict[int, Optional[Dict[str, Any]]] = {}
        self._image_cache: Dict[int, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers = {"x-api-key": self.api_key}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=self.timeout,
                )

                # レート制限(429)の場合は待って再試行
                if response.status_code == 429:
                    wait = self.retry_wait_seconds * attempt
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.RequestException as exc:
                last_error = exc
                time.sleep(self.retry_wait_seconds)

        raise EtsyAPIError(f"Etsy APIへのリクエストに失敗しました: {last_error}")

    # ------------------------------------------------------------------
    # 公開メソッド (MVP)
    # ------------------------------------------------------------------
    def search_active_listings(
        self,
        keyword: str,
        limit: int = 25,
        max_results: int = 100,
        sort_on: str = "score",
        sort_order: str = "desc",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        キーワードでアクティブな商品(listing)を検索する。

        Args:
            keyword: 検索キーワード
            limit: 1回のAPIリクエストあたりの取得件数 (最大100)
            max_results: 取得したい商品の合計件数(ページングして取得)
            sort_on: 並び替え基準 (score, created, price, updated)
            sort_order: asc / desc
            extra_params: Etsy APIにそのまま渡す追加パラメータ (例: min_price など)

        Returns:
            listing情報(dict)のリスト
        """
        results: List[Dict[str, Any]] = []
        offset = 0
        limit = min(limit, 100)

        while len(results) < max_results:
            params: Dict[str, Any] = {
                "keywords": keyword,
                "limit": limit,
                "offset": offset,
                "sort_on": sort_on,
                "sort_order": sort_order,
            }
            if extra_params:
                params.update(extra_params)

            data = self._get("/listings/active", params=params)
            batch = data.get("results", [])
            if not batch:
                break

            results.extend(batch)
            offset += limit

            # Etsy側の総件数を超えたら終了
            total_count = data.get("count", 0)
            if offset >= total_count:
                break

        return results[:max_results]

    # ------------------------------------------------------------------
    # Phase2: 画像 / ショップ情報の取得 (キャッシュ付き)
    # ------------------------------------------------------------------
    def get_listing_images(self, listing_id: int, use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        指定したlistingの画像情報を取得する (GET /listings/{listing_id}/images)。

        画像1件ごとに url_75x75 / url_170x135 / url_570xN / url_fullxfull といった
        サイズ違いのURLに加え、hex_code / brightness などの色情報も含まれる。

        同じlisting_idに対しては2回目以降キャッシュを返す(APIコール削減)。
        """
        if use_cache and listing_id in self._image_cache:
            return self._image_cache[listing_id]

        try:
            data = self._get(f"/listings/{listing_id}/images")
            images = data.get("results", []) or []
        except EtsyAPIError:
            # 画像取得に失敗しても全体の処理は止めず、空リストとして扱う
            images = []

        self._image_cache[listing_id] = images
        return images

    def get_shop(self, shop_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        ショップ情報を取得する (GET /shops/{shop_id})。

        同じshop_idに対しては2回目以降キャッシュを返す(APIコール削減)。
        取得に失敗した場合は None を返す(全体の処理は止めない)。
        """
        if use_cache and shop_id in self._shop_cache:
            return self._shop_cache[shop_id]

        try:
            shop = self._get(f"/shops/{shop_id}")
        except EtsyAPIError:
            shop = None

        self._shop_cache[shop_id] = shop
        return shop

    def enrich_listings(
        self,
        raw_listings: List[Dict[str, Any]],
        fetch_shop: bool = True,
        fetch_images: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        listing一覧に対して、ショップ情報・画像情報を付与する。

        - shop_idが同じ商品が複数あっても、get_shopのキャッシュにより
          ショップ情報のAPIコールは実際には shop_idごとに1回だけ発生する。
        - 画像取得(get_listing_images)はlisting_idごとに1回発生する
          (Etsy APIにlisting横断で画像をまとめて取る手段がないため)。
          商品件数が多いとAPIコール数がその分増える点に注意。

        raw_listings の各dictに以下のキーを直接追加して返す(破壊的変更):
          - shop_name, shop_url  (ショップ情報が取れた場合のみ)
          - images               (画像情報のリスト。取れない場合は空リスト)
        """
        for listing in raw_listings:
            shop_id = listing.get("shop_id")
            listing_id = listing.get("listing_id")

            if fetch_shop and shop_id is not None:
                shop = self.get_shop(shop_id)
                if shop:
                    listing["shop_name"] = shop.get("shop_name")
                    listing["shop_url"] = shop.get("url")

            if fetch_images and listing_id is not None:
                listing["images"] = self.get_listing_images(listing_id)

        return raw_listings

    # ------------------------------------------------------------------
    # 対象外(今回のスコープでは実装しない)
    # ------------------------------------------------------------------
    def get_listing_reviews(self, listing_id: int) -> List[Dict[str, Any]]:
        """
        [対象外]
        レビュー取得エンドポイント(getReviewsByListing)はOAuth必須で、
        実質的にショップ所有者本人のトークンでないとアクセスできないため、
        競合分析用途には使えない。そのため今回は未実装のままとする。
        """
        raise NotImplementedError(
            "レビュー分析は公式APIの制約(OAuth必須・競合分析に不向き)により対象外です。"
        )
