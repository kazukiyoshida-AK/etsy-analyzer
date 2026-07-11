"""
interfaces/html_parsers/base.py
---------------------------------
HTMLDataSourceが使う、サイト別パーサーの共通インターフェース。

サイトごとのDOM構造・構造化データの違いはこのインターフェースの
実装側(例: etsy.py)に閉じ込め、HTMLDataSource自体はどのサイトの
HTMLかを意識しない設計にする。将来Etsy以外のサイトに対応する場合も、
このインターフェースを実装したパーサーを追加するだけでよい。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class HTMLListingParser(ABC):
    """保存済みHTML文字列を商品情報のdictのリストへ変換するパーサー。"""

    @abstractmethod
    def parse(self, html: str) -> List[Dict[str, Any]]:
        """
        HTML文字列を解析し、商品情報のdictのリストを返す。

        各dictは interfaces.schema.CANONICAL_FIELDS のフィールド名を
        キーとする想定。取得できなかったフィールドはキー自体を
        省略してよい(HTMLDataSource側でNone/空リストに埋められる)。

        'raw' キーに、抽出元の生データ(例: 解析したJSON-LDオブジェクトの
        中身)を入れておくことを推奨する。
        """
        raise NotImplementedError
