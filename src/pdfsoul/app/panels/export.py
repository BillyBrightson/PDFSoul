"""PDF → Word, Excel, PowerPoint, text/Markdown/HTML, PDF/A, grayscale; OCR; anything → PDF."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QLabel, QRadioButton, QWidget

from pdfsoul.app.jobs import JobSpec
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.widgets import FileListWidget, OutputPicker, PageRangeEdit, muted
from pdfsoul.core import convert, engines, export, ocr, to_pdf
from pdfsoul.core.document import open_pdf
from pdfsoul.core.types import PdfSoulError, Result


def note(text: str, warn: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Warn" if warn else "Note")
    label.setWordWrap(True)
    return label


def radio_group(owner: QWidget, labels: list[str]) -> tuple[QButtonGroup, QWidget]:
    from PySide6.QtWidgets import QVBoxLayout

    group = QButtonGroup(owner)
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    for n, label in enumerate(labels):
        button = QRadioButton(label)
        group.addButton(button, n)
        box.addWidget(button)
    group.button(0).setChecked(True)
    return group, holder


class FromPdfPanel(ToolPanel):
    """One PDF in, one file out, with a page range."""

    tag = ""
    ext = ".pdf"
    file_filter = "PDF files (*.pdf)"
    page_range = True
    warn_if_scanned = False

    def build(self) -> None:
        self.scanned_note = note("This PDF looks scanned, so there is little real text to "
                                 "convert. Run OCR first for a much better result.", warn=True)
        self.scanned_note.hide()
        self.form.addRow(self.scanned_note)
        if self.page_range:
            self.pages = PageRangeEdit()
            self.form.addRow("Pages", self.pages)
        self.add_options()
        self.output = OutputPicker("file", self._default_output, file_filter=self.file_filter)
        self.form.addRow("Save to", self.output)

    def add_options(self) -> None:
        """Extra options, added between the page range and the output."""

    def page_text(self) -> str:
        return self.pages.text() if self.page_range else ""

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, self.tag, self.ext) if path else None

    def document_changed(self) -> None:
        self.output.reset()
        self.scanned_note.setVisible(self.warn_if_scanned and self._looks_scanned())

    def _looks_scanned(self) -> bool:
        path = self.ctx.session.path
        if path is None:
            return False
        try:
            with open_pdf(path, self.password) as doc:
                sample = [doc[i] for i in range(min(doc.page_count, 3))]
                return not any(ocr.has_text(page) for page in sample)
        except PdfSoulError:
            return False

    def on_result(self, result: Result) -> None:
        self.output.reset()


class PdfToWordPanel(FromPdfPanel):
    tool_id = "to_word"
    title = "PDF to Word"
    blurb = ("Rebuilds paragraphs, fonts, tables and images as an editable Word document. "
             "Large files can take a minute.")
    primary_label = "Convert to Word"
    tag, ext, file_filter = "word", ".docx", "Word documents (*.docx)"
    warn_if_scanned = True

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Converting to Word", export.pdf_to_word, [self.source], output,
                       export.PdfToWordOptions(pages=self.page_text(), password=self.password))


class PdfToExcelPanel(FromPdfPanel):
    tool_id = "to_excel"
    title = "PDF to Excel"
    blurb = ("Finds the tables in your PDF and puts them in a spreadsheet. Numbers become real "
             "numbers, so formulas work on them.")
    primary_label = "Convert to Excel"
    tag, ext, file_filter = "excel", ".xlsx", "Excel workbooks (*.xlsx)"
    warn_if_scanned = True

    def add_options(self) -> None:
        self.modes, holder = radio_group(self, ["One sheet per table",
                                                "One sheet per page (tables or text lines)"])
        self.form.addRow("Sheets", holder)

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        mode = [export.ExcelMode.TABLES, export.ExcelMode.PAGES][self.modes.checkedId()]
        return JobSpec("Converting to Excel", export.pdf_to_excel, [self.source], output,
                       export.PdfToExcelOptions(pages=self.page_text(), mode=mode,
                                                password=self.password))


class PdfToPowerPointPanel(FromPdfPanel):
    tool_id = "to_powerpoint"
    title = "PDF to PowerPoint"
    blurb = ("Each page becomes a slide sized to match, looking exactly like the PDF. The "
             "page's text goes into the speaker notes.")
    primary_label = "Convert to PowerPoint"
    tag, ext, file_filter = "slides", ".pptx", "PowerPoint presentations (*.pptx)"

    def add_options(self) -> None:
        self.quality = QComboBox()
        for label, dpi in (("Standard · smaller file (150 dpi)", 150),
                           ("High · recommended (200 dpi)", 200),
                           ("Print · large file (300 dpi)", 300)):
            self.quality.addItem(label, dpi)
        self.quality.setCurrentIndex(1)
        self.form.addRow("Slide quality", self.quality)
        self.notes = QCheckBox("Put each page's text in the speaker notes")
        self.notes.setChecked(True)
        self.form.addRow(self.notes)

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Converting to PowerPoint", export.pdf_to_powerpoint, [self.source],
                       output, export.PdfToPowerPointOptions(
                           pages=self.page_text(), dpi=self.quality.currentData(),
                           notes=self.notes.isChecked(), password=self.password))


TEXT_FORMATS = [
    ("Plain text (.txt)", "text", ".txt", "Text files (*.txt)"),
    ("Markdown (.md)", "markdown", ".md", "Markdown (*.md)"),
    ("Web page (.html)", "web", ".html", "Web pages (*.html)"),
]


class PdfToTextPanel(FromPdfPanel):
    tool_id = "to_text"
    title = "PDF to Text & Markdown"
    blurb = ("Plain text, Markdown with headings, lists and tables, or a single self-contained "
             "web page.")
    primary_label = "Convert"
    tag, ext, file_filter = "text", ".txt", "Text files (*.txt)"
    warn_if_scanned = True

    def add_options(self) -> None:
        self.formats, holder = radio_group(self, [f[0] for f in TEXT_FORMATS])
        self.form.addRow("Format", holder)
        self.html_mode = QComboBox()
        self.html_mode.addItem("Reflowing text · reads well on any screen",
                               export.HtmlMode.REFLOW)
        self.html_mode.addItem("Exact layout · positioned like the PDF", export.HtmlMode.LAYOUT)
        self.form.addRow("Web page style", self.html_mode)
        self.formats.idToggled.connect(lambda *_: self._format_changed())

    def build(self) -> None:
        super().build()
        self._format_changed()

    def _format_changed(self) -> None:
        index = max(self.formats.checkedId(), 0)
        _, self.tag, self.ext, self.file_filter = TEXT_FORMATS[index]
        self.form.setRowVisible(self.html_mode, index == 2)
        if hasattr(self, "output"):
            self.output.set_filter(self.file_filter)
            self.output.reset()

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        index = self.formats.checkedId()
        pages, password = self.page_text(), self.password
        if index == 0:
            return JobSpec("Extracting text", convert.extract_text, [self.source], output,
                           convert.ExtractTextOptions(pages=pages, password=password))
        if index == 1:
            return JobSpec("Converting to Markdown", export.pdf_to_markdown, [self.source],
                           output, export.PdfToMarkdownOptions(pages=pages, password=password))
        return JobSpec("Converting to HTML", export.pdf_to_html, [self.source], output,
                       export.PdfToHtmlOptions(pages=pages, mode=self.html_mode.currentData(),
                                               password=password))


class PdfaPanel(FromPdfPanel):
    tool_id = "pdfa"
    title = "PDF to PDF/A"
    blurb = ("The ISO archiving format that courts, governments and libraries ask for: fonts "
             "embedded, colours fixed, nothing that depends on outside resources.")
    primary_label = "Convert to PDF/A"
    tag = "pdfa"
    page_range = False

    def add_options(self) -> None:
        levels = list(export.PdfaLevel)
        self.levels, holder = radio_group(self, [export.PDFA_LABELS[lv] for lv in levels])
        self.levels.button(levels.index(export.PdfaLevel.A2B)).setChecked(True)
        self.form.addRow("Conformance", holder)
        self.engine_note = note("")
        self.form.addRow(self.engine_note)

    def refresh(self) -> None:
        found = engines.find("gs") is not None
        self.engine_note.setObjectName("Note" if found else "Warn")
        self.engine_note.setText("Uses Ghostscript." if found else
                                 "PDF/A needs Ghostscript. Install it, or set its path in "
                                 "Settings.")
        self.engine_note.style().unpolish(self.engine_note)
        self.engine_note.style().polish(self.engine_note)
        super().refresh()

    def can_run(self) -> bool:
        return engines.find("gs") is not None

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        level = list(export.PdfaLevel)[self.levels.checkedId()]
        return JobSpec("Converting to PDF/A", export.to_pdfa, [self.source], output,
                       export.PdfaOptions(level=level, password=self.password))


class GrayscalePanel(FromPdfPanel):
    tool_id = "grayscale"
    title = "Grayscale PDF"
    blurb = ("Turns every colour into a shade of gray, for cheaper printing. Text stays sharp "
             "and searchable.")
    primary_label = "Convert to grayscale"
    tag = "gray"
    page_range = False

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Converting to grayscale", export.to_grayscale, [self.source], output,
                       export.GrayscaleOptions(password=self.password))


class OcrPanel(FromPdfPanel):
    tool_id = "ocr"
    title = "OCR · make searchable"
    blurb = ("Recognises the text in scanned pages and adds it invisibly, so you can search, "
             "select and copy. The pages look exactly the same.")
    primary_label = "Run OCR"
    tag = "ocr"

    def add_options(self) -> None:
        self.language = QComboBox()
        self.form.addRow("Language", self.language)
        self.dpi = QComboBox()
        for label, dpi in (("Fast (200 dpi)", 200), ("Accurate · recommended (300 dpi)", 300),
                           ("Small print (400 dpi)", 400)):
            self.dpi.addItem(label, dpi)
        self.dpi.setCurrentIndex(1)
        self.form.addRow("Quality", self.dpi)
        self.skip = QCheckBox("Skip pages that already have text")
        self.skip.setChecked(True)
        self.form.addRow(self.skip)
        self.engine_note = note("", warn=True)
        self.form.addRow(self.engine_note)
        self._languages: list[str] | None = None

    def refresh(self) -> None:
        if self._languages is None or not self._languages:
            self._languages = ocr.languages()
            current = self.language.currentData()
            self.language.clear()
            codes = sorted(self._languages, key=lambda c: (c != "eng", ocr.language_label(c)))
            for code in codes:
                self.language.addItem(ocr.language_label(code), code)
            if "eng" in codes and len(codes) > 1:
                for code in codes[1:4]:
                    self.language.addItem(f"English + {ocr.language_label(code)}",
                                          f"eng+{code}")
            if current:
                self.language.setCurrentIndex(max(self.language.findData(current), 0))
        missing = engines.find("tesseract") is None
        self.engine_note.setVisible(missing)
        self.engine_note.setText("OCR needs Tesseract. Install it (on Windows: the UB Mannheim "
                                 "installer; on macOS: brew install tesseract), or set its path "
                                 "in Settings.")
        super().refresh()

    def can_run(self) -> bool:
        return bool(self._languages) if hasattr(self, "_languages") else False

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Recognising text", ocr.ocr, [self.source], output,
                       ocr.OcrOptions(language=self.language.currentData() or "eng",
                                      dpi=self.dpi.currentData(), pages=self.page_text(),
                                      skip_text_pages=self.skip.isChecked(),
                                      password=self.password))


class ToPdfPanel(ToolPanel):
    """A list of files in, one merged PDF (or one PDF each) out."""

    extensions: set[str] = to_pdf.ALL_EXTENSIONS
    needs_document = False
    primary_label = "Convert to PDF"
    show_layout = True

    def build(self) -> None:
        self.files = FileListWidget(self.extensions, to_pdf.file_filter(self.extensions))
        self.files.changed.connect(self._files_changed)
        self.form.addRow(self.files)
        self.merge = QCheckBox("Combine everything into one PDF")
        self.merge.setChecked(True)
        self.merge.toggled.connect(lambda _: self._files_changed())
        self.form.addRow(self.merge)
        self.paper = QComboBox()
        self.paper.addItem("A4", "a4")
        self.paper.addItem("US Letter", "letter")
        self.form.addRow("Paper size", self.paper)
        self.landscape = QCheckBox("Landscape")
        self.form.addRow(self.landscape)
        self.form.setRowVisible(self.paper, self.show_layout)
        self.form.setRowVisible(self.landscape, self.show_layout)
        self.add_notes()
        self.file_output = OutputPicker("file", self._default_file)
        self.folder_output = OutputPicker("folder", self._default_folder)
        self.form.addRow("Save to", self.file_output)
        self.form.addRow("Save into", self.folder_output)
        self._files_changed()

    def add_notes(self) -> None:
        """Engine status notes for subclasses."""

    def add_files(self, paths: list[Path]) -> None:
        self.files.add_paths(paths)

    def _single_output(self) -> bool:
        return self.merge.isChecked() or len(self.files.paths()) <= 1

    def _files_changed(self) -> None:
        single = self._single_output()
        self.form.setRowVisible(self.merge, len(self.files.paths()) > 1)
        self.form.setRowVisible(self.file_output, single)
        self.form.setRowVisible(self.folder_output, not single)
        self.file_output.refresh()
        self.folder_output.refresh()
        if hasattr(self, "primary"):
            self._update_state()

    def _default_file(self) -> Path | None:
        paths = self.files.paths() if hasattr(self, "files") else []
        if not paths:
            return None
        tag = "merged" if len(paths) > 1 else "converted"
        path = self.ctx.settings.output_for(paths[0], tag)
        return path

    def _default_folder(self) -> Path | None:
        paths = self.files.paths() if hasattr(self, "files") else []
        return self.ctx.settings.folder_for(paths[0], "pdf") if paths else None

    def can_run(self) -> bool:
        return hasattr(self, "files") and bool(self.files.paths())

    def make_job(self) -> JobSpec:
        paths = self.files.paths()
        if not paths:
            raise PdfSoulError("Add at least one file.")
        single = self._single_output()
        output = (self.file_output if single else self.folder_output).path()
        assert output is not None
        return JobSpec(f"Converting {len(paths)} file{'s' if len(paths) > 1 else ''}",
                       to_pdf.to_pdf, paths, output,
                       to_pdf.ToPdfOptions(merge=single, paper=self.paper.currentData(),
                                           landscape=self.landscape.isChecked()))

    def on_result(self, result: Result) -> None:
        self.file_output.reset()
        self.folder_output.reset()


class OfficeToPdfPanel(ToPdfPanel):
    tool_id = "office_to_pdf"
    title = "Word, Excel & PowerPoint to PDF"
    blurb = "DOCX, DOC, XLSX, XLS, CSV, PPTX, PPT, ODT, ODS, ODP and RTF."
    extensions = to_pdf.OFFICE_EXTENSIONS

    def add_notes(self) -> None:
        self.engine_note = note("")
        self.form.addRow(self.engine_note)

    def refresh(self) -> None:
        found = engines.find("soffice") is not None
        self.engine_note.setObjectName("Note" if found else "Warn")
        self.engine_note.setText(
            "Using LibreOffice: the layout matches the original exactly." if found else
            "LibreOffice isn't installed, so DOCX, XLSX, CSV and PPTX use the built-in "
            "converter (content and tables kept, layout simplified). Older formats such as DOC "
            "and PPT need LibreOffice from libreoffice.org.")
        self.engine_note.style().unpolish(self.engine_note)
        self.engine_note.style().polish(self.engine_note)
        self.form.setRowVisible(self.paper, not found)
        self.form.setRowVisible(self.landscape, not found)
        super().refresh()


class DocsToPdfPanel(ToPdfPanel):
    tool_id = "docs_to_pdf"
    title = "Web, text & eBook to PDF"
    blurb = ("HTML pages, Markdown, plain text, ePub, MOBI, FB2, XPS, comic books (CBZ), SVG "
             "and images.")
    extensions = to_pdf.WEB_EXTENSIONS | to_pdf.EBOOK_EXTENSIONS | convert.IMAGE_EXTENSIONS

    def add_notes(self) -> None:
        self.form.addRow(muted("Web pages convert offline: images load from the page's folder, "
                               "never from the internet."))
