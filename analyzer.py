"""
analyzer.py
-----------
Etsy APIから取得した生データ(listing)を整形・分析・保存するモジュール。

Phase1: 生データ -> DataFrame整形 / 基本統計 / CSV・Excel保存
Phase2:
  - normalize_listing に shop_name / shop_url / 画像関連フィールドを追加
    (事前に etsy_api.EtsyAPIClient.enrich_listings() で
     各listingのdictに shop_name / shop_url / images が
     付与されている前提)
  - score_listing による「人気度スコア」の算出

注意(重要): score は num_favorers・検索順位・鮮度・キーワード一致などから
算出した「相対的な人気度の推定値」であり、実際の販売数やレビュー評価を
示すものではない。公式APIでは販売数・レビュー数・星評価を競合分析用途で
取得できないため、それらの代わりに使える指標として設計している。

今後の拡張ポイント (AI分析) は EtsyAnalyzer クラスに
プレースホルダーメソッドとして用意してあるので、
実装時はそれぞれのメソッドの中身を追加していく想定。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

import pandas as pd

# Etsyの仕様上の目安値(スコア計算の正規化に使用)
MAX_TAGS = 13          # Etsyで1商品に設定できるタグの上限
MAX_IMAGES = 10        # Etsyで1商品に設定できる画像の上限


def _pick_primary_image(images: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """画像リストから代表画像(rank最小、なければ先頭)を選ぶ。"""
    if not images:
        return None
    try:
        return min(images, key=lambda img: img.get("rank", 0) or 0)
    except (TypeError, ValueError):
        return images[0]


def _best_image_url(image: Dict[str, Any]) -> Optional[str]:
    """画像1件から、できるだけ大きいサイズのURLを選んで返す。"""
    for key in ("url_fullxfull", "url_570xN", "url_170x135", "url_75x75"):
        if image.get(key):
            return image[key]
    return None


def normalize_listing(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Etsy APIから返ってくる1件分の生データ(dict)を、
    分析・出力しやすいフラットな辞書に変換する。

    shop_name / shop_url / images は、事前に
    EtsyAPIClient.enrich_listings() が raw に付与している想定
    (付与されていない場合は None / 空値になる)。
    """
    price_info = raw.get("price", {}) or {}
    amount = price_info.get("amount")
    divisor = price_info.get("divisor") or 1
    price = (amount / divisor) if amount is not None else None

    tags = raw.get("tags", []) or []
    images = raw.get("images", []) or []
    primary_image = _pick_primary_image(images)

    return {
        "listing_id": raw.get("listing_id"),
        "title": raw.get("title"),
        "url": raw.get("url"),
        "price": price,
        "currency_code": price_info.get("currency_code"),
        "quantity": raw.get("quantity"),
        "tags": "; ".join(tags),
        "tag_count": len(tags),
        "materials": "; ".join(raw.get("materials", []) or []),
        "shop_id": raw.get("shop_id"),
        "shop_name": raw.get("shop_name"),
        "shop_url": raw.get("shop_url"),
        "num_favorers": raw.get("num_favorers"),
        "featured_rank": raw.get("featured_rank"),
        "when_made": raw.get("when_made"),
        "who_made": raw.get("who_made"),
        "is_customizable": raw.get("is_customizable"),
        "taxonomy_id": raw.get("taxonomy_id"),
        "creation_timestamp": raw.get("creation_timestamp"),
        "last_modified_timestamp": raw.get("last_modified_timestamp"),
        "description": raw.get("description"),
        "primary_image_url": _best_image_url(primary_image) if primary_image else None,
        "image_count": len(images),
        "image_color_hex": primary_image.get("hex_code") if primary_image else None,
        "image_brightness": primary_image.get("brightness") if primary_image else None,
    }


class EtsyAnalyzer:
    """
    Etsy商品データの整形・分析・保存をまとめて担当するクラス。

    使い方:
        analyzer = EtsyAnalyzer(raw_listings, keyword="cat mug")
        analyzer.save_csv("output/result.csv")
        analyzer.save_excel("output/result.xlsx")
        summary = analyzer.basic_stats()

    keyword を渡すと、score_listing によるスコア計算時に
    「タイトル/タグ/商品説明にキーワードが含まれているか」も
    スコアの一要素として利用される。
    """

    def __init__(self, raw_listings: List[Dict[str, Any]], keyword: Optional[str] = None):
        self.raw_listings = raw_listings
        self.keyword = keyword
        self.df: pd.DataFrame = self._build_dataframe(raw_listings)
        self.score_listing(keyword=keyword)

    # ------------------------------------------------------------------
    # データ整形
    # ------------------------------------------------------------------
    @staticmethod
    def _build_dataframe(raw_listings: List[Dict[str, Any]]) -> pd.DataFrame:
        rows = [normalize_listing(item) for item in raw_listings]
        df = pd.DataFrame(rows)
        return df

    # ------------------------------------------------------------------
    # MVP: 基本分析
    # ------------------------------------------------------------------
    def basic_stats(self) -> Dict[str, Any]:
        """
        価格帯・タグ頻出度など、最低限の基本統計をまとめて返す。
        """
        if self.df.empty:
            return {"count": 0}

        price_series = self.df["price"].dropna()

        tag_counter: Counter = Counter()
        for tags_str in self.df["tags"].dropna():
            for tag in [t.strip() for t in tags_str.split(";") if t.strip()]:
                tag_counter[tag] += 1

        stats: Dict[str, Any] = {
            "count": len(self.df),
            "price_min": price_series.min() if not price_series.empty else None,
            "price_max": price_series.max() if not price_series.empty else None,
            "price_mean": round(price_series.mean(), 2) if not price_series.empty else None,
            "price_median": price_series.median() if not price_series.empty else None,
            "unique_shops": self.df["shop_id"].nunique(),
            "top_tags": tag_counter.most_common(20),
        }
        return stats

    def summary_dataframe(self) -> pd.DataFrame:
        """
        basic_stats() の結果を、Excel/CSVに書き出しやすい
        縦持ちのDataFrameに変換する(トップタグを除く)。
        """
        stats = self.basic_stats()
        top_tags = stats.pop("top_tags", [])

        summary_rows = [{"metric": key, "value": value} for key, value in stats.items()]
        summary_df = pd.DataFrame(summary_rows)

        if top_tags:
            tag_df = pd.DataFrame(top_tags, columns=["tag", "count"])
        else:
            tag_df = pd.DataFrame(columns=["tag", "count"])

        return summary_df, tag_df

    # ------------------------------------------------------------------
    # スコアリング (人気度の推定)
    # ------------------------------------------------------------------
    @staticmethod
    def _minmax_normalize(series: pd.Series, invert: bool = False) -> pd.Series:
        """
        取得できた商品群の中での相対的な位置(0〜1)に正規化する。

        Etsy APIは母集団全体の統計(全商品中の順位など)を返さないため、
        「今回検索でヒットした商品同士を比べてどう位置するか」という
        相対評価にせざるを得ない。全件が同値の場合は中立値0.5を返す。
        invert=True の場合は値が小さいほど高スコアになるよう反転する。
        """
        series = series.astype(float)
        min_v, max_v = series.min(), series.max()
        if pd.isna(min_v) or pd.isna(max_v) or min_v == max_v:
            return pd.Series(0.5, index=series.index)
        normalized = (series - min_v) / (max_v - min_v)
        return (1 - normalized) if invert else normalized

    def _keyword_match_score(self, keyword: Optional[str]) -> pd.Series:
        """
        キーワードがタイトル/タグ/商品説明に含まれるかをスコア化する。
        タイトル一致を最も重視し、タグ・説明文の一致も加点する。
        keywordが指定されない場合は中立値0.5を全件に返す。
        """
        if not keyword:
            return pd.Series(0.5, index=self.df.index)

        needle = keyword.strip().lower()
        if not needle:
            return pd.Series(0.5, index=self.df.index)

        title = self.df["title"].fillna("").str.lower()
        tags = self.df["tags"].fillna("").str.lower()
        description = self.df["description"].fillna("").str.lower()

        title_match = title.str.contains(needle, regex=False).astype(float)
        tags_match = tags.str.contains(needle, regex=False).astype(float)
        description_match = description.str.contains(needle, regex=False).astype(float)

        return (title_match * 0.6) + (tags_match * 0.25) + (description_match * 0.15)

    def score_listing(self, keyword: Optional[str] = None) -> pd.DataFrame:
        """
        各商品の「人気度スコア(0〜100)」を算出し、self.dfに 'score' 列として追加する。

        重要: このスコアは実際の販売数やレビュー評価を示すものではない。
        公式APIでは競合分析用途で販売数・レビュー数・星評価を取得できないため、
        代わりに以下の要素を組み合わせた「相対的な人気度の推定値」としている。

          - num_favorers        : お気に入り数 (多いほど高評価)
          - featured_rank       : 検索内の掲載順位 (良い順位ほど高評価)
          - price               : 価格 (今回は「手に取りやすい価格帯ほど高評価」として設計)
          - tag_count           : 設定タグ数 (Etsy上限13に対する充足率。SEO対策度の目安)
          - image_count         : 画像枚数 (Etsy上限10に対する充足率。掲載充実度の目安)
          - last_modified_timestamp : 更新の新しさ (直近で更新されているほど高評価)
          - keyword_match       : キーワードがタイトル/タグ/説明文に含まれるか

        価格を「安いほど高評価」とする設計は一つの考え方に過ぎない
        (高価格帯でも売れている=ブランド力がある、という見方もできるため)。
        分析目的に応じて重みや向きを調整すること。
        """
        if self.df.empty:
            self.df["score"] = pd.Series(dtype=float)
            return self.df

        weights = {
            "num_favorers": 0.20,
            "featured_rank": 0.10,
            "price": 0.10,
            "tag_count": 0.10,
            "image_count": 0.10,
            "freshness": 0.15,
            "keyword_match": 0.25,
        }

        fav_score = self._minmax_normalize(self.df["num_favorers"].fillna(0))

        # featured_rankは値が小さいほど良い掲載順位という想定で反転する
        rank_series = self.df["featured_rank"]
        rank_filled = rank_series.fillna(rank_series.max() if rank_series.notna().any() else 0)
        rank_score = self._minmax_normalize(rank_filled, invert=True)

        # 価格は安いほど高評価(手に取りやすさ重視の設計。上記docstring参照)
        price_series = self.df["price"]
        price_filled = price_series.fillna(price_series.median() if price_series.notna().any() else 0)
        price_score = self._minmax_normalize(price_filled, invert=True)

        tag_score = (self.df["tag_count"].fillna(0) / MAX_TAGS).clip(upper=1.0)
        image_score = (self.df["image_count"].fillna(0) / MAX_IMAGES).clip(upper=1.0)

        freshness_series = self.df["last_modified_timestamp"].fillna(0)
        freshness_score = self._minmax_normalize(freshness_series)

        keyword_score = self._keyword_match_score(keyword)

        total_score = (
            fav_score * weights["num_favorers"]
            + rank_score * weights["featured_rank"]
            + price_score * weights["price"]
            + tag_score * weights["tag_count"]
            + image_score * weights["image_count"]
            + freshness_score * weights["freshness"]
            + keyword_score * weights["keyword_match"]
        )

        self.df["score"] = (total_score * 100).round(2)
        return self.df

    def top_listings(self, n: int = 10) -> pd.DataFrame:
        """スコア降順で上位n件を返す(表示用の補助メソッド)。"""
        if self.df.empty or "score" not in self.df.columns:
            return self.df
        return self.df.sort_values("score", ascending=False).head(n)

    # ------------------------------------------------------------------
    # 保存機能
    # ------------------------------------------------------------------
    def save_csv(self, path: str) -> str:
        """listing一覧をスコア降順でCSVに保存する。"""
        df_sorted = self.df.sort_values("score", ascending=False) if "score" in self.df.columns else self.df
        df_sorted.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    def save_excel(self, path: str) -> str:
        """
        listing一覧 + サマリーをExcelに保存する。
        シート構成:
          - listings: 商品一覧 (スコア降順)
          - summary : 基本統計
          - top_tags: 頻出タグランキング
        """
        summary_df, tag_df = self.summary_dataframe()
        df_sorted = self.df.sort_values("score", ascending=False) if "score" in self.df.columns else self.df

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_sorted.to_excel(writer, sheet_name="listings", index=False)
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            tag_df.to_excel(writer, sheet_name="top_tags", index=False)

        return path

    # ------------------------------------------------------------------
    # 将来の拡張用プレースホルダー
    # ------------------------------------------------------------------
    def analyze_reviews(self, reviews: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        [未実装 / 将来の拡張用]
        レビュー分析(評価分布、キーワード抽出、感情分析など)を行う。

        想定インプット: etsy_api.EtsyAPIClient.get_listing_reviews() の戻り値
        """
        raise NotImplementedError("レビュー分析機能は今後実装予定です。")

    def analyze_images(self, image_urls: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        [未実装 / 将来の拡張用]
        商品画像の詳細分析(構図、被写体、サムネイル傾向のAI分析など)を行う。

        代表画像の色味(image_color_hex) / 明るさ(image_brightness) / 枚数(image_count)は
        Phase2で normalize_listing / score_listing に既に組み込み済み。
        ここでは、画像そのもの(ダウンロードして構図や被写体を解析するなど)を
        使ったより踏み込んだ分析を今後実装する想定。
        """
        raise NotImplementedError("画像の詳細分析機能は今後実装予定です。")

    def analyze_with_ai(self, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        [未実装 / 将来の拡張用]
        LLM(Claude等)を使ったタイトル/タグ/売れ筋傾向の分析を行う。
        """
        raise NotImplementedError("AI分析機能は今後実装予定です。")
