"""pytest-qt smoke tests: the real main window, driven offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pymupdf as fitz
import pytest
from conftest import PASSWORD
from PIL import Image
from PySide6.QtCore import QSettings

from pdfsoul.app import dialogs, main_window
from pdfsoul.app.main_window import MainWindow
from pdfsoul.app.settings import Settings
from pdfsoul.app.theme import apply_theme


@pytest.fixture
def window(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    settings = Settings(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.show()
    yield win
    win.runner.wait()
    win.session.pages.mark_saved()  # never prompt on teardown


@pytest.fixture
def doc(fixtures, tmp_path) -> Path:
    """A private copy, so saves land in tmp_path."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(fixtures["simple"].read_bytes())
    return target


def wait_for_job(qtbot, win: MainWindow) -> None:
    qtbot.waitUntil(lambda: not win.runner.busy, timeout=30_000)


def test_starts_on_home(window):
    assert window.centre.currentWidget() is window.home
    assert not window.options.isVisible()


def test_open_shows_viewer_and_pages(window, doc):
    assert window.open_file(doc)
    assert window.centre.currentWidget() is window._viewer_page
    assert window.page_total.text().strip() == "/ 10"
    assert window.settings.recent_files[0] == doc.resolve()
    window.viewer.goto_page(4)
    assert window.viewer.current_page == 4


def test_open_encrypted_asks_for_password(window, fixtures, monkeypatch):
    answers = iter(["wrong", PASSWORD])
    monkeypatch.setattr(main_window, "ask_password", lambda *a, **k: next(answers))
    assert window.open_file(fixtures["encrypted"])
    assert window.session.password == PASSWORD


def test_open_corrupted_file_repairs(window, fixtures):
    assert window.open_file(fixtures["corrupted"])
    assert len(window.session.pages) == 10


def test_viewer_renders_visible_pages(window, doc, qtbot):
    window.open_file(doc)
    qtbot.waitUntil(lambda: window.session.cached_page(
        0, window.viewer.zoom * window.viewer.devicePixelRatioF()) is not None, timeout=5000)


def test_search_finds_matches(window, doc, qtbot):
    window.open_file(doc)
    window.show_search()
    window.search_edit.setText("quick brown")
    window._start_search()
    qtbot.waitUntil(lambda: window.search_status.text() == "1 of 10", timeout=5000)
    window._step_match(1)
    assert window.search_status.text() == "2 of 10"
    window.search_case.setChecked(True)  # "quick brown" is lower-case in the file: still 10
    qtbot.waitUntil(lambda: window.search_status.text().endswith("of 10"), timeout=5000)


def test_organiser_edit_undo_and_save(window, doc, qtbot):
    window.open_file(doc)
    window.select_tool("organise")
    assert window.centre.currentWidget() is window._organiser_page
    window.organiser.select_rows([0, 1])
    window.rotate(90)
    window.organiser.select_rows([9])
    window.delete_pages()
    assert len(window.session.pages) == 9 and window.session.dirty
    window.session.undo()
    assert len(window.session.pages) == 10
    window.session.redo()
    assert window.save()
    wait_for_job(qtbot, window)
    saved = doc.with_name("doc_edited.pdf")
    qtbot.waitUntil(lambda: window.session.path == saved.resolve(), timeout=5000)
    with fitz.open(saved) as out:
        assert out.page_count == 9
        assert [out[0].rotation, out[1].rotation, out[2].rotation] == [90, 90, 0]
    assert doc.exists() and fitz.open(doc).page_count == 10  # original untouched
    assert not window.session.dirty


def test_compress_panel_runs_job(window, fixtures, tmp_path, qtbot):
    src = tmp_path / "scan.pdf"
    src.write_bytes(fixtures["scanned"].read_bytes())
    window.open_file(src)
    window.select_tool("compress")
    panel = window.panels["compress"]
    panel.presets.button(0).setChecked(True)
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert panel.result.isVisible()
    assert (tmp_path / "scan_compressed.pdf").exists()
    assert "smaller" in panel.result._message.text()


def test_merge_panel(window, fixtures, tmp_path, qtbot):
    window.select_tool("merge")
    panel = window.panels["merge"]
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(fixtures["simple"].read_bytes())
    b.write_bytes(fixtures["form"].read_bytes())
    panel.add_files([a, b])
    panel.files.tree.topLevelItem(0).setText(1, "1-2")
    assert panel.primary.isEnabled()
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert fitz.open(tmp_path / "a_merged.pdf").page_count == 3


def test_errors_show_in_result_card(window, doc, qtbot):
    window.open_file(doc)
    window.select_tool("split")
    panel = window.panels["split"]
    panel.ranges_mode.setChecked(True)
    panel.ranges.setText("50-60")
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert panel.result.property("error") is True
    assert "out of range" in panel.result._message.text()


def test_watermark_preview_renders(window, doc, qtbot):
    window.open_file(doc)
    window.select_tool("watermark")
    panel = window.panels["watermark"]
    panel.text.setText("SOUL")
    qtbot.waitUntil(lambda: panel.preview.pixmap() is not None
                    and not panel.preview.pixmap().isNull(), timeout=5000)


def test_dropping_images_routes_to_images_to_pdf(window, tmp_path):
    imgs = []
    for n in range(2):
        path = tmp_path / f"{n}.png"
        Image.new("RGB", (50, 50), "red").save(path)
        imgs.append(path)
    window.handle_dropped(imgs)
    assert window._tool == "images_to_pdf"
    assert window.panels["images_to_pdf"].files.paths() == imgs


def test_dropping_several_pdfs_routes_to_merge(window, fixtures):
    window.handle_dropped([fixtures["simple"], fixtures["form"]])
    assert window._tool == "merge"
    assert len(window.panels["merge"].files.paths()) == 2


def test_dropping_office_and_web_files_routes_to_converters(window, tmp_path):
    docx, md = tmp_path / "a.docx", tmp_path / "b.md"
    docx.write_bytes(b"")
    md.write_text("# hi")
    window.handle_dropped([docx])
    assert window._tool == "office_to_pdf"
    assert window.panels["office_to_pdf"].files.paths() == [docx]
    window.handle_dropped([md])
    assert window._tool == "docs_to_pdf"


def test_docs_to_pdf_panel_runs(window, tmp_path, qtbot):
    a, b = tmp_path / "a.md", tmp_path / "b.txt"
    a.write_text("# Alpha\n")
    b.write_text("beta\n")
    window.select_tool("docs_to_pdf")
    panel = window.panels["docs_to_pdf"]
    panel.add_files([a, b])
    assert panel.merge.isVisibleTo(panel)
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert fitz.open(tmp_path / "a_merged.pdf").page_count == 2
    panel.merge.setChecked(False)
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert sorted(p.name for p in (tmp_path / "a_pdf").iterdir()) == ["a.pdf", "b.pdf"]


@pytest.mark.parametrize("tool,name", [("to_word", "doc_word.docx"),
                                       ("to_excel", "doc_excel.xlsx"),
                                       ("to_powerpoint", "doc_slides.pptx"),
                                       ("grayscale", "doc_gray.pdf")])
def test_from_pdf_panels_run(window, doc, qtbot, tool, name):
    window.open_file(doc)
    window.select_tool(tool)
    panel = window.panels[tool]
    if hasattr(panel, "pages"):
        panel.pages.setText("1-2")
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert panel.result.property("error") is False, panel.result._message.text()
    assert (doc.parent / name).exists()


def test_text_panel_switches_format(window, doc, qtbot):
    window.open_file(doc)
    window.select_tool("to_text")
    panel = window.panels["to_text"]
    panel.formats.button(1).setChecked(True)
    assert panel.output.path().suffix == ".md"
    panel.primary.click()
    wait_for_job(qtbot, window)
    assert (doc.parent / "doc_markdown.md").read_text().strip()
    panel.formats.button(2).setChecked(True)
    assert panel.output.path().suffix == ".html"
    assert panel.html_mode.isVisibleTo(panel)


def test_scanned_pdf_warns_before_word(window, fixtures, tmp_path):
    src = tmp_path / "scan.pdf"
    src.write_bytes(fixtures["scanned"].read_bytes())
    window.open_file(src)
    window.select_tool("to_word")
    assert window.panels["to_word"].scanned_note.isVisibleTo(window.panels["to_word"])


def test_home_search_filters_tools(window):
    home = window.home
    home.search.setText("excel")
    visible = [row.tool.id for row in home.rows if row.isVisibleTo(home)]
    assert visible == ["to_excel", "office_to_pdf"]
    home.search.setText("zzzz")
    assert home.no_match.isVisibleTo(home)
    home.search.setText("")
    assert all(row.isVisibleTo(home) for row in home.rows)


def test_theme_switch_retints(window, qapp):
    from pdfsoul.app import theme

    apply_theme(qapp, "dark")
    assert theme.is_dark()
    apply_theme(qapp, "light")
    assert not theme.is_dark()
    apply_theme(qapp, "system")


def test_unexpected_crash_shows_error_dialog(window, qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr(main_window, "show_error", lambda *a: shown.append(a))
    from pdfsoul.app.jobs import JobSpec

    def boom(*_):
        raise RuntimeError("kaboom")

    window.run_job(JobSpec("Boom", boom, [], Path("x")))
    wait_for_job(qtbot, window)
    qtbot.waitUntil(lambda: bool(shown), timeout=3000)
    assert "kaboom" in shown[0][1] and "Traceback" in shown[0][2]


def test_error_dialog_copy_details(qtbot):
    dialog = dialogs.ErrorDialog(None, "Short message", "Long traceback")
    qtbot.addWidget(dialog)
    dialog._copy("Short message", "Long traceback", dialogs.QPushButton())
    from PySide6.QtGui import QGuiApplication

    assert "Long traceback" in QGuiApplication.clipboard().text()


def test_organiser_drag_reorder(window, doc):
    from PySide6.QtCore import QModelIndex, Qt

    window.open_file(doc)
    window.select_tool("organise")
    model = window.thumb_model
    mime = model.mimeData([model.index(0, 0)])
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert [r.source for r in window.session.pages][:4] == [1, 2, 0, 3]
    assert window.organiser.selected_rows() == [2]
    window.session.undo()
    assert [r.source for r in window.session.pages][:3] == [0, 1, 2]


def test_about_dialog_credits_billy(window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel

    assert window.windowTitle() == "PDFSoul By Billy"
    shown = []
    monkeypatch.setattr(dialogs.AboutDialog, "exec", lambda self: shown.append(self))
    window.about_button.click()
    window.home.credit.click()
    assert len(shown) == 2

    about = shown[0]
    text = " ".join(label.text() for label in about.findChildren(QLabel))
    assert "Billy Brightson" in text
    assert "FREE FOR PERSONAL AND COMMERCIAL USE" in text
    for _ in range(5):
        about._mark.clicked.emit()
    assert about._quote.text() == dialogs.SECRET
