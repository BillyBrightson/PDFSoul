import pymupdf as fitz
from conftest import PASSWORD
from typer.testing import CliRunner

from pdfsoul.cli.main import app

runner = CliRunner()


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["merge", "split", "compress", "rotate", "delete", "extract", "reorder",
                    "insert-blank", "duplicate", "images-to-pdf", "to-images", "text", "images",
                    "watermark", "number", "protect", "unlock", "repair", "info", "engines",
                    "convert", "to-pdf", "ocr"]:
        assert command in result.output


def test_convert_to_office_and_web_formats(fixtures, tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(fixtures["simple"].read_bytes())
    for target, name in [("docx", "a_word.docx"), ("xlsx", "a_excel.xlsx"),
                         ("pptx", "a_slides.pptx"), ("md", "a_markdown.md"),
                         ("html", "a_web.html"), ("txt", "a_text.txt")]:
        result = runner.invoke(app, ["convert", str(src), "--to", target, "--pages", "1-2"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / name).exists()
    result = runner.invoke(app, ["convert", str(src), "--to", "svg", "--pages", "1"])
    assert result.exit_code == 0 and (tmp_path / "a_images" / "a_p001.svg").exists()


def test_to_pdf_merges_and_separates(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.txt"
    a.write_text("# A\n")
    b.write_text("bee\n")
    result = runner.invoke(app, ["to-pdf", str(a), str(b), "-o", str(tmp_path / "ab.pdf")])
    assert result.exit_code == 0, result.output
    assert fitz.open(tmp_path / "ab.pdf").page_count == 2
    folder = tmp_path / "each"
    result = runner.invoke(app, ["to-pdf", str(a), str(b), "--separate", "-o", str(folder)])
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in folder.iterdir()) == ["a.pdf", "b.pdf"]


def test_ocr_skips_text_pages(fixtures, tmp_path):
    from pdfsoul.core import engines

    if engines.find("tesseract") is None:
        return
    result = runner.invoke(app, ["ocr", str(fixtures["simple"]), "--pages", "1",
                                 "-o", str(tmp_path / "o.pdf")])
    assert result.exit_code == 0, result.output
    assert "already had text" in result.output


def test_merge_with_ranges(fixtures, tmp_path):
    out = tmp_path / "m.pdf"
    result = runner.invoke(app, ["merge", f"{fixtures['simple']}:1-2", str(fixtures["form"]),
                                 "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert fitz.open(out).page_count == 3


def test_default_output_never_overwrites(fixtures, tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(fixtures["simple"].read_bytes())
    for _ in range(2):
        assert runner.invoke(app, ["rotate", str(src)]).exit_code == 0
    assert (tmp_path / "a_rotated.pdf").exists() and (tmp_path / "a_rotated (2).pdf").exists()


def test_refuses_to_overwrite_input_without_flag(fixtures, tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(fixtures["simple"].read_bytes())
    result = runner.invoke(app, ["rotate", str(src), "-o", str(src)])
    assert result.exit_code == 2
    result = runner.invoke(app, ["rotate", str(src), "-o", str(src), "--overwrite"])
    assert result.exit_code == 0
    assert fitz.open(src)[0].rotation == 90


def test_failure_exit_code(fixtures, tmp_path):
    result = runner.invoke(app, ["delete", str(fixtures["simple"]), "--pages", "99",
                                 "-o", str(tmp_path / "x.pdf")])
    assert result.exit_code == 1
    assert "out of range" in result.output


def test_encrypted_input_with_password(fixtures, tmp_path):
    result = runner.invoke(app, ["text", str(fixtures["encrypted"]), "-p", PASSWORD,
                                 "-o", str(tmp_path / "t.txt")])
    assert result.exit_code == 0, result.output
    assert "Page 1 of the sample" in (tmp_path / "t.txt").read_text()


def test_encrypted_input_without_password_fails_cleanly(fixtures, tmp_path):
    result = runner.invoke(app, ["text", str(fixtures["encrypted"]),
                                 "-o", str(tmp_path / "t.txt")])
    assert result.exit_code == 1
    assert "password" in result.output.lower()


def test_protect_and_info(fixtures, tmp_path):
    out = tmp_path / "p.pdf"
    result = runner.invoke(app, ["protect", str(fixtures["simple"]), "--password", "pw",
                                 "-o", str(out)])
    assert result.exit_code == 0, result.output
    info = runner.invoke(app, ["info", str(out), "-p", "pw"])
    assert "Encrypted:  yes" in info.output and "Pages:      10" in info.output


def test_split_and_compress(fixtures, tmp_path):
    result = runner.invoke(app, ["split", str(fixtures["simple"]), "--mode", "bookmarks",
                                 "-o", str(tmp_path / "parts")])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "parts").glob("*.pdf"))) == 3
    result = runner.invoke(app, ["compress", str(fixtures["scanned"]), "--preset", "low",
                                 "-o", str(tmp_path / "c.pdf")])
    assert result.exit_code == 0, result.output
    assert "smaller" in result.output
