from pathlib import Path

import pytest

from pdfsoul.core.ranges import format_ranges, parse_page_set, parse_pages, parse_ranges
from pdfsoul.core.safe_io import atomic_output, derive_output, safe_filename, unique_path
from pdfsoul.core.types import PdfSoulError


def test_parse_ranges_groups_in_written_order():
    assert parse_ranges("1-3,5,8-", 10) == [[0, 1, 2], [4], [7, 8, 9]]


def test_parse_ranges_blank_means_all():
    assert parse_ranges("", 3) == [[0, 1, 2]]


def test_open_ended_and_reverse_ranges():
    assert parse_pages("-2", 5) == [0, 1]
    assert parse_pages("4-2", 5) == [3, 2, 1]
    assert parse_pages("end", 5) == [4]


def test_page_set_dedupes_and_sorts():
    assert parse_page_set("3,1,3,2", 5) == [0, 1, 2]


@pytest.mark.parametrize("spec", ["0", "11", "a", "2-x"])
def test_bad_ranges_raise_clear_errors(spec):
    with pytest.raises(PdfSoulError):
        parse_ranges(spec, 10)


def test_format_ranges_round_trip():
    assert format_ranges([0, 1, 2, 4, 7, 8]) == "1-3,5,8-9"
    assert parse_page_set(format_ranges([0, 1, 2, 4]), 10) == [0, 1, 2, 4]


def test_atomic_output_replaces_only_on_success(tmp_path: Path):
    target = tmp_path / "out.txt"
    target.write_text("original")
    with pytest.raises(RuntimeError), atomic_output(target) as tmp:
        tmp.write_text("half written")
        raise RuntimeError("crash")
    assert target.read_text() == "original"
    assert list(tmp_path.iterdir()) == [target]  # temp file cleaned up

    with atomic_output(target) as tmp:
        tmp.write_text("new")
    assert target.read_text() == "new"


def test_output_naming(tmp_path: Path):
    src = tmp_path / "report.pdf"
    assert derive_output(src, "compressed").name == "report_compressed.pdf"
    assert derive_output(src, "text", ".txt", tmp_path / "x").parent == tmp_path / "x"
    src.write_bytes(b"x")
    assert unique_path(src).name == "report (2).pdf"


def test_safe_filename():
    assert safe_filename('Chapter 1: "Intro"/Part?') == "Chapter 1_ _Intro_Part"
    assert safe_filename("...") == "untitled"
