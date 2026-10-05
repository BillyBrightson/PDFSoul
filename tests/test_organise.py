import time
from pathlib import Path
from threading import Event

import pymupdf as fitz
import pytest
from conftest import PASSWORD, first_lines

from pdfsoul.core import organise
from pdfsoul.core.organise import PageRef
from pdfsoul.core.pagelist import PageList
from pdfsoul.core.types import Cancelled, PasswordRequired, PdfSoulError, WrongPassword


def test_merge_keeps_order_and_bookmarks(fixtures, out):
    target = out / "merged.pdf"
    result = organise.merge([fixtures["simple"], fixtures["form"], fixtures["simple"]], target)
    assert result.outputs == [target]
    with fitz.open(target) as doc:
        assert doc.page_count == 21
        toc = doc.get_toc(simple=True)
    # simple.pdf keeps its own bookmarks; form.pdf (none) gets one entry named after the file.
    assert [1, "Introduction", 1] in toc
    assert [1, "form", 11] in toc
    assert [1, "Results", 18] in toc


def test_merge_with_page_ranges(fixtures, out):
    target = out / "m.pdf"
    organise.merge([fixtures["simple"], fixtures["simple"]], target,
                   organise.MergeOptions(page_ranges=["1-2", "10"]))
    assert first_lines(target) == ["Page 1 of the sample", "Page 2 of the sample",
                                   "Page 10 of the sample"]


def test_merge_encrypted_needs_password(fixtures, out):
    with pytest.raises(PasswordRequired):
        organise.merge([fixtures["encrypted"]], out / "x.pdf")
    opts = organise.MergeOptions(passwords={str(fixtures["encrypted"]): PASSWORD})
    organise.merge([fixtures["encrypted"], fixtures["simple"]], out / "x.pdf", opts)
    with fitz.open(out / "x.pdf") as doc:
        assert doc.page_count == 20 and not doc.needs_pass


def test_merge_50_files_is_fast(fixtures, out):
    start = time.perf_counter()
    organise.merge([fixtures["simple"]] * 50, out / "big.pdf")  # 500 pages
    assert time.perf_counter() - start < 10


@pytest.mark.parametrize(("mode", "kwargs", "names"), [
    (organise.SplitMode.EACH_PAGE, {}, [f"simple_p{i}.pdf" for i in range(1, 11)]),
    (organise.SplitMode.RANGES, {"ranges": "1-3,5,8-"},
     ["simple_p1-3.pdf", "simple_p5.pdf", "simple_p8-10.pdf"]),
    (organise.SplitMode.EVERY_N, {"every": 4},
     ["simple_p1-4.pdf", "simple_p5-8.pdf", "simple_p9-10.pdf"]),
    (organise.SplitMode.BOOKMARKS, {},
     ["simple_01_Introduction.pdf", "simple_02_Methods.pdf", "simple_03_Results.pdf"]),
])
def test_split_modes(fixtures, out, mode, kwargs, names):
    result = organise.split([fixtures["simple"]], out, organise.SplitOptions(mode=mode, **kwargs))
    assert [p.name for p in result.outputs] == names
    assert all(p.exists() for p in result.outputs)


def test_split_by_bookmarks_page_spans(fixtures, out):
    result = organise.split([fixtures["simple"]], out,
                            organise.SplitOptions(mode=organise.SplitMode.BOOKMARKS))
    counts = [fitz.open(p).page_count for p in result.outputs]
    assert counts == [3, 3, 4]


def test_split_bookmarks_without_any_errors(fixtures, out):
    with pytest.raises(PdfSoulError, match="no bookmarks"):
        organise.split([fixtures["form"]], out,
                       organise.SplitOptions(mode=organise.SplitMode.BOOKMARKS))


def test_rotate_adds_to_existing_rotation(fixtures, out):
    target = out / "r.pdf"
    organise.rotate([fixtures["rotated"]], target, organise.RotateOptions(pages="1-2", angle=90))
    with fitz.open(target) as doc:
        assert [doc[0].rotation, doc[1].rotation, doc[2].rotation] == [180, 270, 0]


def test_delete_extract_reorder_duplicate_insert(fixtures, out):
    src = [fixtures["simple"]]
    organise.delete_pages(src, out / "d.pdf", organise.PagesOptions(pages="2-10"))
    assert first_lines(out / "d.pdf") == ["Page 1 of the sample"]

    organise.extract_pages(src, out / "e.pdf", organise.PagesOptions(pages="3,1"))
    assert first_lines(out / "e.pdf") == ["Page 3 of the sample", "Page 1 of the sample"]

    organise.reorder(src, out / "o.pdf", organise.PagesOptions(pages="10,9"))
    assert first_lines(out / "o.pdf")[:3] == ["Page 10 of the sample", "Page 9 of the sample",
                                              "Page 1 of the sample"]

    organise.duplicate_pages(src, out / "dup.pdf", organise.PagesOptions(pages="1"))
    assert first_lines(out / "dup.pdf")[:3] == ["Page 1 of the sample"] * 2 + [
        "Page 2 of the sample"]

    organise.insert_blank(src, out / "b.pdf", organise.InsertBlankOptions(after=1, count=2))
    assert first_lines(out / "b.pdf")[:4] == ["Page 1 of the sample", "", "",
                                              "Page 2 of the sample"]


def test_cannot_delete_every_page(fixtures, out):
    with pytest.raises(PdfSoulError):
        organise.delete_pages([fixtures["simple"]], out / "x.pdf",
                              organise.PagesOptions(pages="1-10"))


def test_plan_keeps_bookmarks_pointing_at_moved_pages(fixtures, out):
    plan = [PageRef(6), PageRef(0), PageRef(None)]  # "Results" first, then "Introduction"
    organise.apply_plan([fixtures["simple"]], out / "p.pdf", plan)
    with fitz.open(out / "p.pdf") as doc:
        assert doc.get_toc(simple=True) == [[1, "Introduction", 2], [1, "Results", 1]]
        assert doc.metadata["title"] == "Sample document"


def test_wrong_password(fixtures, out):
    with pytest.raises(WrongPassword):
        organise.rotate([fixtures["encrypted"]], out / "x.pdf",
                        organise.RotateOptions(password="nope"))


def test_cancel_stops_merge(fixtures, out):
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        organise.merge([fixtures["simple"]] * 3, out / "x.pdf", cancel=cancel)
    assert not (out / "x.pdf").exists()


def test_progress_reaches_one(fixtures, out):
    seen: list[float] = []
    organise.merge([fixtures["simple"]] * 3, out / "x.pdf", progress=seen.append)
    assert seen[-1] == 1.0 and seen == sorted(seen)


# --- PageList (organiser model) ------------------------------------------------------------


def test_pagelist_edits_and_undo_redo():
    pl = PageList(5)
    pl.rotate([0], 90)
    pl.delete([1])
    pl.duplicate([0])
    pl.insert_blank(len(pl))
    assert [r.source for r in pl.pages] == [0, 0, 2, 3, 4, None]
    assert pl.pages[0].rotation == 90 and pl.dirty

    assert pl.undo() and pl.undo()
    assert [r.source for r in pl.pages] == [0, 2, 3, 4]
    assert pl.redo()
    assert [r.source for r in pl.pages] == [0, 0, 2, 3, 4]
    pl.rotate([1], 90)
    assert not pl.can_redo  # a new edit clears redo


def test_pagelist_move_returns_new_positions():
    pl = PageList(6)
    assert pl.move([4, 5], 1) == [1, 2]
    assert [r.source for r in pl.pages] == [0, 4, 5, 1, 2, 3]
    assert pl.move([0], 6) == [5]
    assert [r.source for r in pl.pages] == [4, 5, 1, 2, 3, 0]


def test_pagelist_never_deletes_last_page():
    pl = PageList(2)
    pl.delete([0, 1])
    assert len(pl) == 2 and not pl.can_undo


def test_pagelist_blank_matches_neighbour_size():
    pl = PageList(2, sizes=[(612, 792), (300, 400)])
    pl.insert_blank(2)
    assert (pl.pages[2].width, pl.pages[2].height) == (300, 400)


def test_thousand_page_plan_is_fast(fixtures, out):
    pl = PageList(1000)
    pl.move(range(500, 1000), 0)
    pl.rotate(range(0, 1000, 2), 90)
    start = time.perf_counter()
    organise.apply_plan([fixtures["thousand"]], out / "t.pdf", list(pl.pages))
    assert time.perf_counter() - start < 15
    assert first_lines(out / "t.pdf")[0] == "Page 501 of the sample"


def test_open_corrupted_file_is_repaired(fixtures, out):
    organise.extract_pages([fixtures["corrupted"]], out / "fixed.pdf",
                           organise.PagesOptions(pages="1-2"))
    assert first_lines(out / "fixed.pdf") == ["Page 1 of the sample", "Page 2 of the sample"]


def test_missing_file_is_clear_error(out):
    with pytest.raises(PdfSoulError, match="not found"):
        organise.rotate([Path("nope.pdf")], out / "x.pdf", organise.RotateOptions())


def test_non_pdf_is_rejected(tmp_path, out):
    fake = tmp_path / "notes.pdf"
    fake.write_text("# just markdown")
    with pytest.raises(PdfSoulError, match="isn't a PDF"):
        organise.rotate([fake], out / "x.pdf", organise.RotateOptions())
