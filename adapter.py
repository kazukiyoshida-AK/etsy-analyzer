"""
adapter.py
----------
interfaces.DataSource が返す canonical schema (Listing) を、既存の
analyzer.EtsyAnalyzer / analyzer.normalize_listing() が期待する生データの
形へ変換する橋渡し層。

依存関係の方向を明確にするため、以下を守る:
  - analyzer.py           : interfaces を一切importしない
  - interfaces/ 以下       : analyzer.py を一切importしない
  - adapter.py (このファイル): 両方をimportし、変換のみを担う

フィールド名の比較 (2026-07-11時点):
  interfaces.schema.CANONICAL_FIELDS の各フィールド(raw以外)は、
  analyzer.normalize_listing() が raw.get(<同名キー>) で読む値と
  1:1で対応しており、名称・型ともに不一致はない
  (listing_id/title/url/price/quantity/tags/materials/shop_id/
  shop_name/shop_url/num_favorers/featured_rank/when_made/who_made/
  is_customizable/taxonomy_id/creation_timestamp/
  last_modified_timestamp/description/images)。
  唯一の差分は canonical Listing にだけ存在する 'raw'(元データ)で、
  analyzer側では使われないためadapterで除外する。

  この一致は偶然ではなく、canonical schema自体がnormalize_listing()の
  入力契約に合わせて設計されているため。とはいえ将来どちらかが変わった
  場合に備え、変換ロジックはこのファイルに閉じ込めてある
  (tests/test_adapter.py で入出力の整合性を継続的に検証する)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from analyzer import EtsyAnalyzer
from interfaces.schema import CANONICAL_FIELDS, Listing

# canonical Listingのフィールド名 -> analyzer.normalize_listing()が
# raw.get()で読むキー名の対応表。
# 現時点では全フィールドが同名で対応するが、将来どちらかの命名が
# 変わった場合はこの辞書だけを直せばよい。
_FIELD_MAPPING: Dict[str, str] = {
    name: name for name in CANONICAL_FIELDS if name != "raw"
}


def listing_to_raw_dict(listing: Listing) -> Dict[str, Any]:
    """
    canonical Listing 1件を、EtsyAnalyzer/normalize_listing が期待する
    生データdictへ変換する。

    'raw'(取得元の元データ)はanalyzer側で使われないため含めない。
    """
    return {
        analyzer_key: listing.get(canonical_key)
        for canonical_key, analyzer_key in _FIELD_MAPPING.items()
    }


def listings_to_raw_dicts(listings: List[Listing]) -> List[Dict[str, Any]]:
    """canonical Listingのリストを、EtsyAnalyzerへ渡せる生データのリストへ変換する。"""
    return [listing_to_raw_dict(listing) for listing in listings]


def build_analyzer(listings: List[Listing], keyword: Optional[str] = None) -> EtsyAnalyzer:
    """
    canonical Listingのリストから、既存のEtsyAnalyzerを構築する。

    呼び出し側(main.py)はDataSourceの出力を直接EtsyAnalyzerへ渡さず、
    必ずこの関数を経由すること。
    """
    raw_listings = listings_to_raw_dicts(listings)
    return EtsyAnalyzer(raw_listings, keyword=keyword)
