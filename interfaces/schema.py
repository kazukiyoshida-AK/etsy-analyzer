"""
interfaces/schema.py
---------------------
DataSource実装が返す「商品1件分」のdict(canonical schema)を定義するモジュール。

analyzer.EtsyAnalyzer / analyzer.normalize_listing() が読むキー・型に
合わせてある。取得方法(Etsy API / CSV / 保存済みHTML / JSON)によらず、
全てのDataSource実装はこの形へ変換してから listing を返す。

重要: analyzer.py はimportしない(依存しない)。normalize_listing が
期待する入力の形を、ここに独立したドキュメント兼バリデーションとして
明文化し、その"契約"を interfaces 側だけで担保する設計にしている。
analyzer.py 側の実装が将来変わった場合は、このスキーマも合わせて
見直すこと。

欠損値ルール:
  - スカラー値が取得できない場合は None
  - 複数値(tags/materials/images)が取得できない場合は空リスト []
  - 元データは 'raw' キーに必ず保持する(取得方法を問わない共通ルール)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type, TypedDict, Union

# canonical schemaのバージョン。フィールド構成を破壊的に変更する場合は
# ここを上げること(例: "1.0" -> "2.0")。DataSource.schema_version は
# 既定でこの値を参照する(interfaces/datasource.py参照)。
SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class FieldSpec:
    """1フィールド分の型・複数値かどうか・必須かどうかの定義。"""

    types: Tuple[Type, ...]
    is_list: bool = False
    required: bool = False


@dataclass(frozen=True)
class ValidationError:
    """validate_listing() が返す1件分のバリデーションエラー。"""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


# canonical schema本体。
# 'raw' 以外の各フィールドは analyzer.normalize_listing() が
# raw.get(<key>) で読みにいくキーと一対一で対応させてある。
CANONICAL_FIELDS: Dict[str, FieldSpec] = {
    "listing_id": FieldSpec(types=(int,), required=True),
    "title": FieldSpec(types=(str,)),
    "url": FieldSpec(types=(str,)),
    # {"amount": int, "divisor": int, "currency_code": str} を想定
    # (内部キーまでは検証しない。詳細はモジュールdocstring参照)
    "price": FieldSpec(types=(dict,)),
    "quantity": FieldSpec(types=(int,)),
    "tags": FieldSpec(types=(str,), is_list=True),
    "materials": FieldSpec(types=(str,), is_list=True),
    "shop_id": FieldSpec(types=(int, str)),
    "shop_name": FieldSpec(types=(str,)),
    "shop_url": FieldSpec(types=(str,)),
    "num_favorers": FieldSpec(types=(int,)),
    "featured_rank": FieldSpec(types=(int,)),
    "when_made": FieldSpec(types=(str,)),
    "who_made": FieldSpec(types=(str,)),
    "is_customizable": FieldSpec(types=(bool,)),
    "taxonomy_id": FieldSpec(types=(int,)),
    "creation_timestamp": FieldSpec(types=(int,)),
    "last_modified_timestamp": FieldSpec(types=(int,)),
    "description": FieldSpec(types=(str,)),
    # 各要素: {"rank": int, "url_fullxfull": str, ...} を想定
    "images": FieldSpec(types=(dict,), is_list=True),
    # 変換元の生データ。取得方法によらず必ず保持する。
    "raw": FieldSpec(types=(dict,), required=True),
}

REQUIRED_KEYS = frozenset(name for name, spec in CANONICAL_FIELDS.items() if spec.required)
ALL_KEYS = frozenset(CANONICAL_FIELDS)


class Listing(TypedDict):
    """
    fetch_listings() が返す商品1件分の型(canonical schema, version=SCHEMA_VERSION)。

    TypedDictは型チェッカー/IDE向けの静的な型情報でしかなく、実体は
    ただのdictである。そのため analyzer.normalize_listing() はこれまで
    通り raw.get(key) で読み取れる(analyzer.pyへの依存は発生しない)。

    フィールド構成はCANONICAL_FIELDSと必ず一致させること。整合性は
    tests/test_datasource_schema.py で検証している。
    """

    listing_id: Optional[int]
    title: Optional[str]
    url: Optional[str]
    price: Optional[Dict[str, Any]]
    quantity: Optional[int]
    tags: List[str]
    materials: List[str]
    shop_id: Optional[Union[int, str]]
    shop_name: Optional[str]
    shop_url: Optional[str]
    num_favorers: Optional[int]
    featured_rank: Optional[int]
    when_made: Optional[str]
    who_made: Optional[str]
    is_customizable: Optional[bool]
    taxonomy_id: Optional[int]
    creation_timestamp: Optional[int]
    last_modified_timestamp: Optional[int]
    description: Optional[str]
    images: List[Dict[str, Any]]
    raw: Dict[str, Any]


def empty_listing(raw: Optional[Dict[str, Any]] = None) -> Listing:
    """
    欠損値ルールに従った空のcanonical listingを返す。

    DataSource実装は基本的にこの関数の戻り値をベースに、
    取得できたフィールドだけを上書きしていく想定
    (= 取得できなかったフィールドは自動的にNone/[]になる)。
    """
    listing: Dict[str, Any] = {
        name: ([] if spec.is_list else None)
        for name, spec in CANONICAL_FIELDS.items()
        if name != "raw"
    }
    listing["raw"] = raw if raw is not None else {}
    return listing  # type: ignore[return-value]


def _type_name(value: Any) -> str:
    return type(value).__name__


def _types_label(types: Tuple[Type, ...]) -> str:
    return " または ".join(t.__name__ for t in types)


def validate_listing(listing: Dict[str, Any]) -> List[ValidationError]:
    """
    listingがcanonical schemaを満たすか検証する。

    確認する内容:
      - 必須キー(listing_id, raw)が存在し、Noneでないこと
      - 各キーの値が定義された型(またはNone)であること
      - list系フィールドの各要素が定義された型であること
      - canonical schemaに存在しない未知のキーを含んでいないこと

    Returns:
        ValidationErrorのリスト(field: 問題のあったフィールド名,
        message: 人が読んで分かる説明)。空リストなら違反なし。
    """
    errors: List[ValidationError] = []

    for name, spec in CANONICAL_FIELDS.items():
        if name not in listing:
            if spec.required:
                errors.append(ValidationError(field=name, message="必須フィールドですが存在しません"))
            continue

        value = listing[name]

        if spec.is_list:
            if not isinstance(value, list):
                errors.append(
                    ValidationError(
                        field=name,
                        message=f"リスト型である必要がありますが、{_type_name(value)}型でした",
                    )
                )
                continue
            for i, element in enumerate(value):
                if not isinstance(element, spec.types):
                    errors.append(
                        ValidationError(
                            field=f"{name}[{i}]",
                            message=(
                                f"要素は{_types_label(spec.types)}型である必要がありますが、"
                                f"{_type_name(element)}型でした"
                            ),
                        )
                    )
            continue

        if value is None:
            if spec.required:
                errors.append(
                    ValidationError(field=name, message="必須フィールドですが値がNoneです")
                )
            continue

        if not isinstance(value, spec.types):
            errors.append(
                ValidationError(
                    field=name,
                    message=(
                        f"{_types_label(spec.types)}型またはNoneである必要がありますが、"
                        f"{_type_name(value)}型でした"
                    ),
                )
            )

    unknown_keys = set(listing) - ALL_KEYS
    for key in sorted(unknown_keys):
        errors.append(
            ValidationError(field=key, message="canonical schemaに存在しないフィールドです")
        )

    return errors
