"""
tests/test_datasource_etsy_api.py
------------------------------------
interfaces.datasource.EtsyAPIDataSource のユニットテスト。

実際のEtsy APIには接続せず、client引数にフェイクのクライアントを
注入してテストする(既存のtests/test_etsy_api.pyと同じ考え方)。
"""

from __future__ import annotations

import pytest

from interfaces.datasource import DataSourceError, EtsyAPIDataSource
from interfaces.schema import validate_listing


class FakeEtsyClient:
    def __init__(self, listings, fail_search=False):
        self._listings = listings
        self.fail_search = fail_search
        self.enrich_called_with = None
        self.session = _FakeSession()

    def search_active_listings(self, keyword, max_results=50, sort_on="score"):
        if self.fail_search:
            raise RuntimeError("simulated Etsy API failure")
        return [dict(item) for item in self._listings[:max_results]]

    def enrich_listings(self, listings):
        self.enrich_called_with = listings
        for listing in listings:
            listing["shop_name"] = "EnrichedShop"
        return listings


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _sample_raw_listing():
    return {
        "listing_id": 555666,
        "title": "Japanese Wall Art Scroll",
        "url": "https://www.etsy.com/listing/555666/japanese-wall-art-scroll",
        "price": {"amount": 4200, "divisor": 100, "currency_code": "USD"},
        "quantity": 2,
        "tags": ["japanese wall art"],
        "materials": ["silk"],
        "shop_id": 9001,
        "num_favorers": 50,
        "featured_rank": 1,
        "when_made": "2020_2026",
        "who_made": "someone_else",
        "is_customizable": False,
        "taxonomy_id": 42,
        "creation_timestamp": 1700200000,
        "last_modified_timestamp": 1750200000,
        "description": "A handcrafted wall scroll.",
        "images": [{"rank": 0, "url_fullxfull": "https://example.com/555666.jpg"}],
    }


def test_fetch_listings_maps_to_canonical_schema_and_enriches():
    client = FakeEtsyClient([_sample_raw_listing()])
    source = EtsyAPIDataSource(client=client)

    listings = source.fetch_listings(keyword="japanese wall art")

    assert len(listings) == 1
    listing = listings[0]
    assert validate_listing(listing) == []
    assert listing["listing_id"] == 555666
    assert listing["shop_name"] == "EnrichedShop"  # enrich_listingsの結果が反映される
    assert client.enrich_called_with is not None
    assert listing["raw"]["listing_id"] == 555666


def test_skip_enrich_does_not_call_enrich_listings():
    client = FakeEtsyClient([_sample_raw_listing()])
    source = EtsyAPIDataSource(client=client)

    listings = source.fetch_listings(keyword="x", skip_enrich=True)

    assert client.enrich_called_with is None
    assert listings[0]["shop_name"] is None


def test_search_failure_is_normalized_to_datasource_error():
    client = FakeEtsyClient([], fail_search=True)
    source = EtsyAPIDataSource(client=client)

    with pytest.raises(DataSourceError):
        source.fetch_listings(keyword="x")


def test_close_closes_underlying_session():
    client = FakeEtsyClient([_sample_raw_listing()])
    source = EtsyAPIDataSource(client=client)

    source.close()

    assert client.session.closed is True


def test_context_manager_closes_session():
    client = FakeEtsyClient([_sample_raw_listing()])

    with EtsyAPIDataSource(client=client) as source:
        source.fetch_listings(keyword="x")

    assert client.session.closed is True


def test_missing_api_key_raises_datasource_error_not_etsy_api_error(monkeypatch):
    monkeypatch.delenv("ETSY_API_KEY", raising=False)
    monkeypatch.delenv("ETSY_ACCESS_TOKEN", raising=False)

    with pytest.raises(DataSourceError):
        EtsyAPIDataSource()
