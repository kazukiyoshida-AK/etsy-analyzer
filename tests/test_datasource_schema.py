"""
tests/test_datasource_schema.py
---------------------------------
interfaces.schema (canonical schema定義・Listing型・empty_listing・
validate_listing・SCHEMA_VERSION) のユニットテスト。
"""

from __future__ import annotations

from interfaces.schema import (
    CANONICAL_FIELDS,
    SCHEMA_VERSION,
    Listing,
    ValidationError,
    empty_listing,
    validate_listing,
)


def test_empty_listing_has_all_canonical_keys():
    listing = empty_listing()
    assert set(listing.keys()) == set(CANONICAL_FIELDS.keys())


def test_empty_listing_defaults_scalars_to_none_and_lists_to_empty():
    listing = empty_listing()
    for name, spec in CANONICAL_FIELDS.items():
        if name == "raw":
            continue
        if spec.is_list:
            assert listing[name] == []
        else:
            assert listing[name] is None


def test_empty_listing_defaults_raw_to_empty_dict_when_omitted():
    listing = empty_listing()
    assert listing["raw"] == {}


def test_empty_listing_keeps_supplied_raw():
    raw = {"source": "unit-test"}
    listing = empty_listing(raw=raw)
    assert listing["raw"] == raw


def test_listing_typed_dict_keys_match_canonical_fields():
    """Listing(TypedDict)とCANONICAL_FIELDSのキー構成がずれていないことを保証する。"""
    assert set(Listing.__annotations__.keys()) == set(CANONICAL_FIELDS.keys())


def test_schema_version_is_defined():
    assert SCHEMA_VERSION == "1.0"
    assert isinstance(SCHEMA_VERSION, str)


def test_validate_listing_valid_case_has_no_errors():
    listing = empty_listing(raw={"x": 1})
    listing["listing_id"] = 123
    listing["title"] = "Sample"
    listing["tags"] = ["a", "b"]
    listing["price"] = {"amount": 1000, "divisor": 100, "currency_code": "USD"}
    assert validate_listing(listing) == []


def test_validate_listing_returns_validation_error_instances():
    listing = empty_listing(raw={})
    listing["listing_id"] = None
    errors = validate_listing(listing)
    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    assert errors[0].field == "listing_id"
    assert "必須" in errors[0].message
    assert str(errors[0]) == "listing_id: 必須フィールドですが値がNoneです"


def test_validate_listing_missing_required_field():
    listing = empty_listing(raw={})
    listing["listing_id"] = None
    errors = validate_listing(listing)
    assert any(e.field == "listing_id" for e in errors)


def test_validate_listing_missing_raw_key_entirely():
    listing = empty_listing(raw={})
    listing["listing_id"] = 1
    del listing["raw"]
    errors = validate_listing(listing)
    assert any(e.field == "raw" and "存在しません" in e.message for e in errors)


def test_validate_listing_wrong_scalar_type():
    listing = empty_listing(raw={})
    listing["listing_id"] = "not-an-int"
    errors = validate_listing(listing)
    assert any(e.field == "listing_id" and "str型でした" in e.message for e in errors)


def test_validate_listing_wrong_list_type():
    listing = empty_listing(raw={})
    listing["listing_id"] = 1
    listing["tags"] = "not-a-list"
    errors = validate_listing(listing)
    assert any(e.field == "tags" for e in errors)


def test_validate_listing_wrong_list_element_type():
    listing = empty_listing(raw={})
    listing["listing_id"] = 1
    listing["tags"] = ["ok", 123]
    errors = validate_listing(listing)
    assert any(e.field == "tags[1]" for e in errors)


def test_validate_listing_rejects_unknown_fields():
    listing = empty_listing(raw={})
    listing["listing_id"] = 1
    listing["not_a_canonical_field"] = "oops"
    errors = validate_listing(listing)
    assert any(
        e.field == "not_a_canonical_field" and "canonical schema" in e.message
        for e in errors
    )


def test_validate_listing_optional_field_none_is_valid():
    listing = empty_listing(raw={})
    listing["listing_id"] = 1
    listing["title"] = None
    assert validate_listing(listing) == []
