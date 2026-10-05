"""Every core operation runs against every fixture (and any real files in tests/fixtures/).

An operation may refuse an input with a clear PdfSoulError, but it must never crash, hang, or
leave a partial output behind.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import PASSWORD

from pdfsoul.core import convert, edit, optimise, organise, secure
from pdfsoul.core.types import PdfSoulError

FIXTURE_NAMES = ["simple", "encrypted", "scanned", "form", "nonlatin", "rotated", "corrupted"]


def _ops(pw: str | None) -> dict[str, Callable[[Path, Path], object]]:
    return {
        "merge": lambda src, out: organise.merge(
            [src, src], out / "o.pdf", organise.MergeOptions(passwords={str(src): pw or ""})),
        "split": lambda src, out: organise.split(
            [src], out, organise.SplitOptions(mode=organise.SplitMode.EVERY_N, every=2,
                                              password=pw)),
        "rotate": lambda src, out: organise.rotate(
            [src], out / "o.pdf", organise.RotateOptions(angle=270, password=pw)),
        "extract": lambda src, out: organise.extract_pages(
            [src], out / "o.pdf", organise.PagesOptions(pages="1", password=pw)),
        "compress": lambda src, out: optimise.compress(
            [src], out / "o.pdf", optimise.CompressOptions(password=pw)),
        "to_images": lambda src, out: convert.pdf_to_images(
            [src], out, convert.PdfToImagesOptions(pages="1", dpi=72, password=pw)),
        "text": lambda src, out: convert.extract_text(
            [src], out / "o.txt", convert.ExtractTextOptions(password=pw)),
        "images": lambda src, out: convert.extract_images(
            [src], out, convert.ExtractImagesOptions(password=pw)),
        "watermark": lambda src, out: edit.watermark(
            [src], out / "o.pdf", edit.WatermarkOptions(text="SOUL", password=pw)),
        "numbers": lambda src, out: edit.page_numbers(
            [src], out / "o.pdf", edit.PageNumberOptions(password=pw)),
        "protect": lambda src, out: secure.protect(
            [src], out / "o.pdf", secure.ProtectOptions(user_password="x", current_password=pw)),
    }


@pytest.mark.parametrize("op", list(_ops(None)))
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_op_on_every_fixture(fixtures, tmp_path, name, op):
    pw = PASSWORD if name == "encrypted" else None
    run = _ops(pw)[op]
    try:
        result = run(fixtures[name], tmp_path)
    except PdfSoulError as exc:
        assert str(exc), "errors must carry a message for the user"
        leftovers = [p for p in tmp_path.rglob("*") if p.name.startswith(".")]
        assert not leftovers, f"partial output left behind: {leftovers}"
        return
    for path in getattr(result, "outputs", []):
        assert path.exists() and path.stat().st_size > 0


def test_real_world_fixtures(fixtures, tmp_path):
    """Drop awkward real PDFs into tests/fixtures/ and they get the full sweep here."""
    real = {k: v for k, v in fixtures.items() if k.startswith("real:")}
    if not real:
        pytest.skip("no real-world PDFs in tests/fixtures/")
    for name, path in real.items():
        for op, run in _ops(None).items():
            target = tmp_path / f"{Path(name).stem}-{op}"
            target.mkdir()
            with contextlib.suppress(PdfSoulError):
                run(path, target)
