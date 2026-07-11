"""
tests/test_main_integration.py
---------------------------------
main.py の統合テスト。

interfaces.DataSource -> adapter.build_analyzer() -> 既存の
EtsyAnalyzer/reporter/exporter/prompt_builder という一連の流れが、
CLI引数(main.parse_args経由)からエンドツーエンドで動くことを検証する。

実際のネットワークアクセス(Etsy API)は行わない。apiソースのテストは
main.EtsyAPIDataSource をフェイク実装に差し替えて検証する。

各テストは tmp_path にchdirしてから実行し、output/ 以下の生成物が
リポジトリ本体を汚さないようにする。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

import main
from interfaces.datasource import DataSource
from interfaces.schema import Listing, empty_listing

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _run_main(monkeypatch, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["main.py"] + argv)
    main.main()


def _output_files(tmp_path, pattern="*"):
    output_dir = tmp_path / "output"
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob(pattern))


def _write_canonical_csv(path: Path, rows) -> None:
    from interfaces.schema import CANONICAL_FIELDS

    columns = [name for name in CANONICAL_FIELDS if name != "raw"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            encoded = {}
            for col in columns:
                value = row.get(col)
                spec = CANONICAL_FIELDS[col]
                if value is None:
                    encoded[col] = ""
                elif spec.is_list or spec.types == (dict,):
                    encoded[col] = json.dumps(value)
                else:
                    encoded[col] = str(value)
            writer.writerow(encoded)


# ----------------------------------------------------------------------
# 1. csv入力から分析・CSV出力まで成功
# ----------------------------------------------------------------------
def test_csv_source_end_to_end_produces_csv_output(monkeypatch, tmp_path):
    csv_path = tmp_path / "listings.csv"
    _write_canonical_csv(
        csv_path,
        [
            {
                "listing_id": 111,
                "title": "Japanese Wall Art Print",
                "price": {"amount": 2500, "divisor": 100, "currency_code": "USD"},
                "tags": ["japanese wall art", "minimalist"],
            }
        ],
    )

    _run_main(
        monkeypatch,
        tmp_path,
        ["--source", "csv", "--input", str(csv_path), "--keyword", "japanese wall art"],
    )

    csv_outputs = _output_files(tmp_path, "*.csv")
    xlsx_outputs = _output_files(tmp_path, "*.xlsx")
    assert len(csv_outputs) == 1
    assert len(xlsx_outputs) == 1

    content = csv_outputs[0].read_text(encoding="utf-8-sig")
    assert "Japanese Wall Art Print" in content


def test_csv_source_with_mapping_file_succeeds(monkeypatch, tmp_path):
    csv_path = tmp_path / "arbitrary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Name"])
        writer.writerow(["222", "Mapped Wall Art"])

    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps({"listing_id": "ID", "title": "Name"}), encoding="utf-8"
    )

    _run_main(
        monkeypatch,
        tmp_path,
        [
            "--source",
            "csv",
            "--input",
            str(csv_path),
            "--mapping",
            str(mapping_path),
            "--keyword",
            "wall art",
        ],
    )

    csv_outputs = _output_files(tmp_path, "*.csv")
    assert len(csv_outputs) == 1
    assert "Mapped Wall Art" in csv_outputs[0].read_text(encoding="utf-8-sig")


# ----------------------------------------------------------------------
# 2. json入力からMarkdownレポート生成まで成功
# ----------------------------------------------------------------------
def test_json_source_end_to_end_produces_markdown_report(monkeypatch, tmp_path):
    json_path = tmp_path / "listings.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "listing_id": 333,
                    "title": "Sumi-e Wall Art",
                    "price": {"amount": 4000, "divisor": 100, "currency_code": "USD"},
                }
            ]
        ),
        encoding="utf-8",
    )

    _run_main(
        monkeypatch,
        tmp_path,
        ["--source", "json", "--input", str(json_path), "--keyword", "sumi-e", "--report"],
    )

    reports = _output_files(tmp_path, "*_report.md")
    assert len(reports) == 1
    report_text = reports[0].read_text(encoding="utf-8")
    assert "sumi-e" in report_text
    assert "Sumi-e Wall Art" in report_text or "スコア上位" in report_text


# ----------------------------------------------------------------------
# 3. html入力からAI向けJSON生成まで成功
# ----------------------------------------------------------------------
def test_html_source_end_to_end_produces_ai_json(monkeypatch, tmp_path):
    html_path = FIXTURES_DIR / "etsy_listing.html"

    _run_main(
        monkeypatch,
        tmp_path,
        [
            "--source",
            "html",
            "--input",
            str(html_path),
            "--keyword",
            "japanese wall art",
            "--json",
        ],
    )

    json_outputs = [p for p in _output_files(tmp_path, "*.json")]
    assert len(json_outputs) == 1

    data = json.loads(json_outputs[0].read_text(encoding="utf-8"))
    assert data["keyword"] == "japanese wall art"
    assert "disclaimer" in data
    assert data["total_count"] == 1


# ----------------------------------------------------------------------
# 4. apiモードが既存の引数で起動できる(後方互換)
# ----------------------------------------------------------------------
class _FakeApiSource(DataSource):
    def fetch_listings(self, keyword, max_results=50, **kwargs):
        listing: Listing = empty_listing(raw={"listing_id": 444})
        listing["listing_id"] = 444
        listing["title"] = "Fake API Listing"
        listing["price"] = {"amount": 1500, "divisor": 100, "currency_code": "USD"}
        return [listing]


def test_api_source_starts_with_existing_arguments(monkeypatch, tmp_path):
    """--sourceを指定せず(=api既定)、旧来の--keywordだけで起動できること。"""
    monkeypatch.setattr(main, "EtsyAPIDataSource", lambda: _FakeApiSource())

    _run_main(monkeypatch, tmp_path, ["--keyword", "cat mug", "--max-results", "10"])

    csv_outputs = _output_files(tmp_path, "*.csv")
    assert len(csv_outputs) == 1
    assert "Fake API Listing" in csv_outputs[0].read_text(encoding="utf-8-sig")


def test_api_source_rejects_input_argument(monkeypatch, tmp_path, capsys):
    """--source api で --input を渡すのは不正な組み合わせ(方針9)。"""
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            tmp_path,
            ["--source", "api", "--input", "somefile.csv", "--keyword", "cat mug"],
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "--input" in captured.out


# ----------------------------------------------------------------------
# 5. --input不足時に適切に失敗する
# ----------------------------------------------------------------------
@pytest.mark.parametrize("source", ["csv", "html", "json"])
def test_missing_input_fails_clearly(monkeypatch, tmp_path, capsys, source):
    with pytest.raises(SystemExit) as exc_info:
        _run_main(monkeypatch, tmp_path, ["--source", source, "--keyword", "x"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "--input" in captured.out
    assert "必須" in captured.out


# ----------------------------------------------------------------------
# 6. canonical schema不正時にValidationError内容を表示する
# ----------------------------------------------------------------------
def test_invalid_canonical_schema_shows_validation_error_details(monkeypatch, tmp_path, capsys):
    json_path = tmp_path / "invalid_listings.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "listing_id": 555,
                    "title": "Broken Listing",
                    "tags": "not-a-list",  # canonical schema違反(list型が必要)
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            tmp_path,
            ["--source", "json", "--input", str(json_path), "--keyword", "x"],
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "canonical schemaに違反しています" in captured.out
    assert "tags" in captured.out
    assert "リスト型である必要があります" in captured.out

    # 不正データのままCSV/Excelが生成されていないこと
    assert _output_files(tmp_path, "*.csv") == []
