"""
tests/test_etsy_api.py
----------------------
etsy_api.EtsyAPIClient のユニットテスト。

実際のEtsy APIには接続せず、EtsyAPIClient._get をモックに差し替えて
リクエスト/レスポンスの流れとキャッシュ挙動のみを検証する。
"""

from __future__ import annotations

import pytest

from etsy_api import EtsyAPIClient, EtsyAPIError


@pytest.fixture
def client() -> EtsyAPIClient:
    """テスト用に api_key を直接渡してインスタンス化する(.env不要)。"""
    return EtsyAPIClient(api_key="dummy-key")


def test_missing_api_key_raises() -> None:
    """api_keyが無い場合はEtsyAPIErrorを送出する。"""
    with pytest.raises(EtsyAPIError):
        EtsyAPIClient(api_key=None, access_token=None)


def test_search_active_listings_paginates(client: EtsyAPIClient) -> None:
    """limit/offsetでのページングが正しく行われ、max_resultsで打ち切られること。"""
    call_log = []

    def fake_get(path, params=None):
        call_log.append(dict(params))
        offset = params["offset"]
        # 全部で25件あるとして、limit=10ずつ返す
        remaining = max(0, 25 - offset)
        batch_size = min(10, remaining)
        batch = [{"listing_id": offset + i} for i in range(batch_size)]
        return {"count": 25, "results": batch}

    client._get = fake_get

    results = client.search_active_listings(keyword="cat", limit=10, max_results=20)

    assert len(results) == 20
    assert [r["listing_id"] for r in results] == list(range(20))
    # offset=0, offset=10 の2回で20件に達するはず
    assert len(call_log) == 2
    assert call_log[0]["offset"] == 0
    assert call_log[1]["offset"] == 10


def test_search_active_listings_stops_when_no_more_results(client: EtsyAPIClient) -> None:
    """APIが空のresultsを返したら、max_resultsに満たなくても打ち切ること。"""

    def fake_get(path, params=None):
        return {"count": 3, "results": [{"listing_id": 1}, {"listing_id": 2}, {"listing_id": 3}]} \
            if params["offset"] == 0 else {"count": 3, "results": []}

    client._get = fake_get
    results = client.search_active_listings(keyword="cat", limit=10, max_results=100)
    assert len(results) == 3


def test_get_shop_uses_cache(client: EtsyAPIClient) -> None:
    """同じshop_idへの2回目以降の呼び出しはAPIコールされないこと。"""
    call_count = {"n": 0}

    def fake_get(path, params=None):
        call_count["n"] += 1
        return {"shop_id": 111, "shop_name": "TestShop", "url": "https://etsy.com/shop/TestShop"}

    client._get = fake_get

    shop1 = client.get_shop(111)
    shop2 = client.get_shop(111)

    assert call_count["n"] == 1  # 2回呼んでもAPIコールは1回だけ
    assert shop1 is shop2
    assert shop1["shop_name"] == "TestShop"


def test_get_shop_bypasses_cache_when_requested(client: EtsyAPIClient) -> None:
    """use_cache=Falseを指定すればキャッシュを無視してAPIを呼ぶこと。"""
    call_count = {"n": 0}

    def fake_get(path, params=None):
        call_count["n"] += 1
        return {"shop_id": 111, "shop_name": "TestShop"}

    client._get = fake_get
    client.get_shop(111)
    client.get_shop(111, use_cache=False)

    assert call_count["n"] == 2


def test_get_shop_returns_none_on_error(client: EtsyAPIClient) -> None:
    """API呼び出しが失敗してもNoneを返し、例外を外に漏らさないこと。"""

    def fake_get(path, params=None):
        raise EtsyAPIError("boom")

    client._get = fake_get
    result = client.get_shop(999)
    assert result is None


def test_get_listing_images_uses_cache(client: EtsyAPIClient) -> None:
    """同じlisting_idへの2回目以降の呼び出しはAPIコールされないこと。"""
    call_count = {"n": 0}

    def fake_get(path, params=None):
        call_count["n"] += 1
        return {"results": [{"listing_id": 1, "rank": 1, "hex_code": "ff0000"}]}

    client._get = fake_get
    images1 = client.get_listing_images(1)
    images2 = client.get_listing_images(1)

    assert call_count["n"] == 1
    assert images1 is images2
    assert images1[0]["hex_code"] == "ff0000"


def test_get_listing_images_returns_empty_list_on_error(client: EtsyAPIClient) -> None:
    """画像取得に失敗しても空リストを返し、全体の処理を止めないこと。"""

    def fake_get(path, params=None):
        raise EtsyAPIError("boom")

    client._get = fake_get
    images = client.get_listing_images(1)
    assert images == []


def test_enrich_listings_dedupes_shop_calls(client: EtsyAPIClient) -> None:
    """
    同じshop_idを持つ複数のlistingがあっても、
    ショップ情報のAPIコールはshop_idごとに1回だけになること。
    """
    shop_calls = {"n": 0}
    image_calls = {"n": 0}

    def fake_get(path, params=None):
        if path.startswith("/shops/"):
            shop_calls["n"] += 1
            shop_id = int(path.split("/")[-1])
            return {"shop_id": shop_id, "shop_name": f"Shop{shop_id}", "url": f"https://etsy.com/shop/{shop_id}"}
        if path.endswith("/images"):
            image_calls["n"] += 1
            listing_id = int(path.split("/")[-2])
            return {"results": [{"listing_id": listing_id, "rank": 1, "hex_code": "abcabc"}]}
        raise AssertionError(f"unexpected path: {path}")

    client._get = fake_get

    raw_listings = [
        {"listing_id": 1, "shop_id": 111},
        {"listing_id": 2, "shop_id": 111},  # 同じショップ
        {"listing_id": 3, "shop_id": 222},
    ]

    client.enrich_listings(raw_listings)

    assert shop_calls["n"] == 2  # ユニークなshop_id(111, 222)の数だけ
    assert image_calls["n"] == 3  # listing_idはすべて異なるので3回

    assert raw_listings[0]["shop_name"] == "Shop111"
    assert raw_listings[1]["shop_name"] == "Shop111"
    assert raw_listings[2]["shop_name"] == "Shop222"
    for listing in raw_listings:
        assert "images" in listing
        assert listing["images"][0]["hex_code"] == "abcabc"


def test_get_listing_reviews_not_implemented(client: EtsyAPIClient) -> None:
    """レビュー取得は今回のスコープ対象外としてNotImplementedErrorを送出すること。"""
    with pytest.raises(NotImplementedError):
        client.get_listing_reviews(1)
