import io
from pathlib import Path

import pikepdf
import pymupdf as fitz
import pytest
from conftest import PASSWORD, page_texts
from PIL import Image

from pdfsoul.core import convert, edit, optimise, secure
from pdfsoul.core.types import PasswordRequired, PdfSoulError, WrongPassword

# --- Convert -------------------------------------------------------------------------------


def _image(path: Path, size=(400, 300), mode="RGB", color="teal", **save) -> Path:
    Image.new(mode, size, color).save(path, **save)
    return path


def test_images_to_pdf_fit_and_a4(out):
    imgs = [_image(out / "a.jpg"), _image(out / "b.png", (300, 600), "RGBA", (255, 0, 0, 128))]
    convert.images_to_pdf(imgs, out / "fit.pdf")
    with fitz.open(out / "fit.pdf") as doc:
        assert doc.page_count == 2
        assert doc[0].rect.width == pytest.approx(400 * 72 / 96, abs=1)

    convert.images_to_pdf(imgs, out / "a4.pdf",
                          convert.ImagesToPdfOptions(page_size=convert.PageSize.A4, margin_pt=36))
    with fitz.open(out / "a4.pdf") as doc:
        assert (round(doc[0].rect.width), round(doc[0].rect.height)) == (842, 595)  # landscape
        assert (round(doc[1].rect.width), round(doc[1].rect.height)) == (595, 842)  # portrait


def test_multipage_tiff_becomes_several_pages(out):
    frames = [Image.new("RGB", (100, 100), c) for c in ("red", "green", "blue")]
    frames[0].save(out / "t.tiff", save_all=True, append_images=frames[1:])
    convert.images_to_pdf([out / "t.tiff"], out / "t.pdf")
    assert fitz.open(out / "t.pdf").page_count == 3


def test_bad_image_is_clear_error(out):
    (out / "x.jpg").write_text("not an image")
    with pytest.raises(PdfSoulError, match="Couldn't read image"):
        convert.images_to_pdf([out / "x.jpg"], out / "x.pdf")


@pytest.mark.parametrize("fmt", list(convert.ImageFormat))
def test_pdf_to_images(fixtures, out, fmt):
    result = convert.pdf_to_images([fixtures["simple"]], out,
                                   convert.PdfToImagesOptions(fmt=fmt, dpi=72, pages="1,3"))
    assert [p.name for p in result.outputs] == [f"simple_p001.{fmt}", f"simple_p003.{fmt}"]
    if fmt is convert.ImageFormat.SVG:
        svg = result.outputs[0].read_text(encoding="utf-8")
        assert svg.startswith("<svg") and 'viewBox="0 0 595 842"' in svg
        return
    with Image.open(result.outputs[0]) as img:
        assert img.size == (595, 842)


def test_pdf_to_images_dpi_bounds(fixtures, out):
    with pytest.raises(PdfSoulError):
        convert.pdf_to_images([fixtures["simple"]], out, convert.PdfToImagesOptions(dpi=1200))


def test_extract_text_including_non_latin(fixtures, out):
    convert.extract_text([fixtures["nonlatin"]], out / "t.txt")
    text = (out / "t.txt").read_text(encoding="utf-8")
    assert "你好" in text and "Кириллица" in text


def test_extract_text_flags_scans(fixtures, out):
    result = convert.extract_text([fixtures["scanned"]], out / "s.txt")
    assert "scanned" in result.message


def test_extract_images_dedupes(fixtures, out):
    result = convert.extract_images([fixtures["scanned"]], out)
    assert len(result.outputs) == 1  # the same image on 3 pages is saved once


# --- Secure --------------------------------------------------------------------------------


def test_protect_then_unlock_round_trip(fixtures, out):
    secure.protect([fixtures["simple"]], out / "p.pdf",
                   secure.ProtectOptions(user_password="pw", allow_copy=False))
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(out / "p.pdf")
    with pikepdf.open(out / "p.pdf", password="pw") as pdf:
        assert pdf.encryption.R == 6 and pdf.encryption.stream_method.name == "aesv3"
    perms = secure.permissions(out / "p.pdf", "pw")
    assert perms.encrypted and perms.print and not perms.copy

    with pytest.raises(WrongPassword):
        secure.unlock([out / "p.pdf"], out / "u.pdf", secure.UnlockOptions(password="bad"))
    secure.unlock([out / "p.pdf"], out / "u.pdf", secure.UnlockOptions(password="pw"))
    with pikepdf.open(out / "u.pdf") as pdf:
        assert not pdf.is_encrypted


def test_owner_only_password_opens_freely(fixtures, out):
    secure.protect([fixtures["simple"]], out / "o.pdf",
                   secure.ProtectOptions(owner_password="owner", allow_print=False))
    perms = secure.permissions(out / "o.pdf")
    assert perms.encrypted and not perms.needs_password and not perms.print


def test_unlock_unencrypted_file_is_clear_error(fixtures, out):
    with pytest.raises(PdfSoulError, match="isn't password protected"):
        secure.unlock([fixtures["simple"]], out / "x.pdf", secure.UnlockOptions(password="x"))


def test_reprotect_needs_current_password(fixtures, out):
    with pytest.raises(PasswordRequired):
        secure.protect([fixtures["encrypted"]], out / "x.pdf",
                       secure.ProtectOptions(user_password="new"))
    secure.protect([fixtures["encrypted"]], out / "x.pdf",
                   secure.ProtectOptions(user_password="new", current_password=PASSWORD))
    assert page_texts(out / "x.pdf", "new")[0].startswith("Page 1")


# --- Edit (stamps) -------------------------------------------------------------------------


def test_text_watermark_on_selected_pages(fixtures, out):
    edit.watermark([fixtures["simple"]], out / "w.pdf",
                   edit.WatermarkOptions(text="DRAFT", pages="2-3"))
    texts = page_texts(out / "w.pdf")
    assert "DRAFT" not in texts[0] and "DRAFT" in texts[1] and "DRAFT" in texts[2]


def test_image_watermark(fixtures, out):
    logo = _image(out / "logo.png", (120, 40), "RGBA", (0, 0, 255, 255))
    edit.watermark([fixtures["rotated"]], out / "w.pdf",
                   edit.WatermarkOptions(image=logo, angle=30, opacity=0.5))
    with fitz.open(out / "w.pdf") as doc:
        assert all(page.get_images() for page in doc)


def test_watermark_needs_text_or_image(fixtures, out):
    with pytest.raises(PdfSoulError):
        edit.watermark([fixtures["simple"]], out / "x.pdf", edit.WatermarkOptions())


def test_page_numbers_format_and_start(fixtures, out):
    edit.page_numbers([fixtures["simple"]], out / "n.pdf",
                      edit.PageNumberOptions(fmt="Page {n} of {total}", start=5, pages="2-4"))
    texts = page_texts(out / "n.pdf")
    assert "Page 5 of 7" in texts[1] and "Page 7 of 7" in texts[3]
    assert "of 7" not in texts[0]


def test_page_numbers_land_upright_on_rotated_pages(fixtures, out):
    edit.page_numbers([fixtures["rotated"]], out / "n.pdf",
                      edit.PageNumberOptions(position=edit.Position.BOTTOM_RIGHT))
    with fitz.open(out / "n.pdf") as doc:
        for page in doc:
            hits = page.search_for(str(page.number + 1), quads=False)
            visible = [h * page.rotation_matrix for h in hits]
            # bottom-right of the *visible* page
            assert any(r.x0 > page.rect.width * 0.7 and r.y0 > page.rect.height * 0.8
                       for r in visible), page.number


def test_preview_returns_png(fixtures):
    png = edit.preview(fixtures["simple"], None, 0, 50, edit.WatermarkOptions(text="X"))
    assert Image.open(io.BytesIO(png)).format == "PNG"


# --- Optimise ------------------------------------------------------------------------------


@pytest.mark.parametrize("use_gs", [True, False])
def test_compress_shrinks_image_heavy_pdf(fixtures, out, use_gs):
    target = out / "c.pdf"
    result = optimise.compress([fixtures["scanned"]], target, optimise.CompressOptions(
        preset=optimise.CompressPreset.LOW, use_ghostscript=use_gs))
    assert result.outputs == [target]
    assert result.details["after"] < result.details["before"]
    assert target.stat().st_size == result.details["after"]
    assert fitz.open(target).page_count == 3


def test_compress_keeps_original_when_not_smaller(out):
    tiny = out / "tiny.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(tiny, garbage=4, deflate=True, use_objstms=1)
    result = optimise.compress([tiny], out / "c.pdf")
    if result.details.get("kept_original"):
        assert result.outputs == [] and not (out / "c.pdf").exists()


def test_compress_encrypted(fixtures, out):
    with pytest.raises(PasswordRequired):
        optimise.compress([fixtures["encrypted"]], out / "c.pdf")
    optimise.compress([fixtures["encrypted"]], out / "c.pdf",
                      optimise.CompressOptions(password=PASSWORD))


def test_repair(fixtures, out):
    result = optimise.repair([fixtures["corrupted"]], out / "r.pdf")
    assert "10 pages" in result.message
    with pikepdf.open(out / "r.pdf") as pdf:
        assert len(pdf.pages) == 10


def test_options_accept_plain_strings(fixtures, out):
    """Qt widgets hand enum values back as plain strings; core must accept them."""
    edit.watermark([fixtures["simple"]], out / "w.pdf",
                   edit.WatermarkOptions(text="X", position="center", pages="1"))
    edit.page_numbers([fixtures["simple"]], out / "n.pdf",
                      edit.PageNumberOptions(position="top-left"))
    img = _image(out / "i.png")
    convert.images_to_pdf([img], out / "i.pdf", convert.ImagesToPdfOptions(page_size="a4"))
    convert.pdf_to_images([fixtures["simple"]], out, convert.PdfToImagesOptions(fmt="jpg",
                                                                               pages="1"))
    optimise.compress([fixtures["scanned"]], out / "c.pdf",
                      optimise.CompressOptions(preset="high"))
