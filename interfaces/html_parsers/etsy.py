"""
interfaces/html_parsers/etsy.py
--------------------------------
保存済みEtsy商品ページHTMLから商品情報を抽出するパーサー。

方針:
  Etsyの商品詳細ページは、多くの場合 schema.org の Product構造化データを
  <script type="application/ld+json"> として埋め込んでいる。
  CSSクラス名などのDOM構造はEtsy側の変更で頻繁に壊れるのに対し、
  構造化データは検索エンジン向けに提供されているぶん比較的安定して
  いるため、これを一次情報源として利用する。

  CSSセレクタによるフォールバック解析は、実際のHTMLサンプルを用いた
  検証が別途必要なため、今回のスコープでは実装しない
  (JSON-LDが見つからない/解析できない場合は空リストを返す)。
  将来追加する場合も、このファイル内に閉じ込めればよい
  (HTMLListingParserインターフェースの実装を差し替えるだけで済む)。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, List, Optional

from .base import HTMLListingParser

_LISTING_ID_PATTERN = re.compile(r"/listing/(\d+)/")
_JSONLD_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


class EtsyHTMLParser(HTMLListingParser):
    """保存済みEtsy商品ページHTMLをJSON-LD(schema.org Product)から解析する。"""

    def parse(self, html: str) -> List[Dict[str, Any]]:
        listings: List[Dict[str, Any]] = []

        for block in _JSONLD_PATTERN.findall(html):
            try:
                data = json.loads(block.strip())
            except json.JSONDecodeError:
                continue

            for product in self._iter_products(data):
                fields = self._product_to_fields(product)
                if fields is not None:
                    listings.append(fields)

        return listings

    @staticmethod
    def _iter_products(data: Any) -> Iterator[Dict[str, Any]]:
        """JSON-LDは単一オブジェクト/配列/@graphなど複数の形を取りうるため正規化する。"""
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict) and "@graph" in data:
            candidates = data["@graph"]
        else:
            candidates = [data]

        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            if item_type == "Product" or (
                isinstance(item_type, list) and "Product" in item_type
            ):
                yield item

    @staticmethod
    def _product_to_fields(product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = product.get("url") or product.get("@id")
        listing_id = None
        if isinstance(url, str):
            match = _LISTING_ID_PATTERN.search(url)
            if match:
                listing_id = int(match.group(1))

        if listing_id is None:
            # canonical schemaではlisting_idが必須のため、取れないものは採用しない
            return None

        offers = product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        offers = offers if isinstance(offers, dict) else {}

        price = None
        raw_price = offers.get("price")
        if raw_price is not None:
            try:
                price = {
                    "amount": int(round(float(raw_price) * 100)),
                    "divisor": 100,
                    "currency_code": offers.get("priceCurrency"),
                }
            except (TypeError, ValueError):
                price = None

        image = product.get("image")
        if isinstance(image, str):
            image = [image]
        images: List[Dict[str, Any]] = []
        if isinstance(image, list):
            for rank, img_url in enumerate(image):
                if isinstance(img_url, str):
                    images.append({"rank": rank, "url_fullxfull": img_url})

        brand = product.get("brand")
        shop_name = None
        if isinstance(brand, dict):
            shop_name = brand.get("name")
        elif isinstance(brand, str):
            shop_name = brand

        return {
            "listing_id": listing_id,
            "title": product.get("name"),
            "url": url,
            "price": price,
            "description": product.get("description"),
            "images": images,
            "shop_name": shop_name,
            "materials": [],
            "tags": [],
            "raw": product,
        }
