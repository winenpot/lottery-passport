"""Pure layout and PDF-rendering checks for scripts/qr_sheets.py."""

import csv
import stat
from pathlib import Path

import pytest

from app.domain.codes import CITY2_B9, format_printed, generate_code, parse_code
from app.domain.passports import CityCode
from scripts.qr_sheets import (
    CSV_HEADER,
    LayoutError,
    page_count,
    paginate,
    plan_grid,
    read_csv_rows,
    render_sheets,
)


def write_batch_csv(path: Path, count: int, *, batch_id: str = "batch-test") -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for _ in range(count):
            code = generate_code(CityCode.TOKYO, CITY2_B9)
            printed = format_printed(code, CITY2_B9)
            writer.writerow(
                [
                    batch_id,
                    "TOKYO",
                    printed,
                    code,
                    f"https://torshx.com/b/{printed}",
                ]
            )


def test_a4_50_per_page_matches_the_documented_grid() -> None:
    plan = plan_grid("A4", 50, 20.0)

    assert (plan.columns, plan.rows) == (5, 10)
    assert plan.cell_width_mm > 20.0
    assert plan.cell_height_mm > 20.0


def test_a3_120_per_page_matches_the_documented_grid() -> None:
    plan = plan_grid("A3", 120, 20.0)

    assert (plan.columns, plan.rows) == (10, 12)


def test_an_oversized_qr_is_refused_not_silently_shrunk() -> None:
    with pytest.raises(LayoutError, match="does not fit"):
        plan_grid("A4", 50, 40.0)


def test_unknown_paper_is_refused() -> None:
    with pytest.raises(LayoutError, match="unknown paper"):
        plan_grid("A5", 10, 20.0)


def test_zero_or_negative_inputs_are_refused() -> None:
    with pytest.raises(LayoutError):
        plan_grid("A4", 0, 20.0)
    with pytest.raises(LayoutError):
        plan_grid("A4", 10, 0.0)


def test_paginate_splits_into_chunks_of_per_page() -> None:
    rows = list(range(23))  # type: ignore[assignment]  # any sequence for this check

    pages = paginate(rows, 10)  # type: ignore[arg-type]

    assert [len(page) for page in pages] == [10, 10, 3]


def test_page_count_rounds_up_and_handles_empty() -> None:
    assert page_count(50, 50) == 1
    assert page_count(51, 50) == 2
    assert page_count(0, 50) == 0


def test_read_csv_rows_rejects_a_wrong_header(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("not,the,right,header\n", encoding="utf-8")

    with pytest.raises(LayoutError, match="expected header"):
        read_csv_rows(bad)


def test_render_sheets_writes_a_private_pdf_with_the_right_page_count(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "batch.csv"
    write_batch_csv(csv_path, 53)
    rows = read_csv_rows(csv_path)
    plan = plan_grid("A4", 50, 20.0)
    output = tmp_path / "sheets.pdf"

    pages = render_sheets(rows, plan, output, batch_id="batch-test")

    assert pages == 2  # 50 + 3
    assert output.read_bytes().startswith(b"%PDF")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_render_sheets_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "batch.csv"
    write_batch_csv(csv_path, 1)
    rows = read_csv_rows(csv_path)
    plan = plan_grid("A4", 50, 20.0)
    output = tmp_path / "sheets.pdf"
    output.write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError):
        render_sheets(rows, plan, output)

    assert output.read_text(encoding="utf-8") == "do not overwrite"


def test_every_csv_qr_url_is_a_code_our_own_parser_accepts(tmp_path: Path) -> None:
    """The payload drawn into each QR must be exactly what redeem() accepts."""
    csv_path = tmp_path / "batch.csv"
    write_batch_csv(csv_path, 5)
    rows = read_csv_rows(csv_path)

    for row in rows:
        from_url = parse_code(row.qr_url).canonical
        from_printed = parse_code(row.printed_code).canonical
        assert from_url == from_printed
