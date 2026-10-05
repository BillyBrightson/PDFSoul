"""One options panel per tool, and the registry the sidebar and home screen are built from."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QIcon, QPixmap

from pdfsoul.app import icons
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.panels.convert import ExtractPanel, ImagesToPdfPanel, ToImagesPanel
from pdfsoul.app.panels.edit import PageNumbersPanel, WatermarkPanel
from pdfsoul.app.panels.export import (
    DocsToPdfPanel,
    GrayscalePanel,
    OcrPanel,
    OfficeToPdfPanel,
    PdfaPanel,
    PdfToExcelPanel,
    PdfToPowerPointPanel,
    PdfToTextPanel,
    PdfToWordPanel,
)
from pdfsoul.app.panels.organise import CompressPanel, MergePanel, OrganisePanel, SplitPanel
from pdfsoul.app.panels.secure import ProtectPanel, UnlockPanel


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    group: str
    glyph: str  # a line icon from icons.PATHS, or a coloured file badge from icons.BADGES
    panel: type[ToolPanel]
    description: str = ""
    on_home: bool = True
    keywords: str = ""

    @property
    def is_badge(self) -> bool:
        return self.glyph in icons.BADGES

    def icon(self, color: QColor | str, selected: QColor | str | None = None,
             size: int = 18) -> QIcon:
        if self.is_badge:
            return icons.badge_icon(self.glyph, size + 2)
        return icons.icon(self.glyph, color, selected, size=size)

    def pixmap(self, color: QColor | str, size: int = 22) -> QPixmap:
        if self.is_badge:
            return icons.badge(self.glyph, size + 2)
        return icons.pixmap(self.glyph, color, size)


ORGANISE, OPTIMISE, EDIT, SECURE = "Organise", "Optimise", "Edit", "Secure"
FROM_PDF, TO_PDF = "Convert from PDF", "Convert to PDF"
GROUPS = [ORGANISE, OPTIMISE, FROM_PDF, TO_PDF, EDIT, SECURE]

# Home screen columns, like "Tools" and "Convert" side by side.
HOME_COLUMNS = [
    ("Tools", [ORGANISE, OPTIMISE, EDIT, SECURE]),
    ("Convert", [FROM_PDF, TO_PDF]),
]

TOOLS = [
    Tool("organise", "Organise pages", ORGANISE, "grid", OrganisePanel,
         "Reorder, rotate, delete and insert pages", keywords="reorder rotate delete pages"),
    Tool("merge", "Merge PDFs", ORGANISE, "copy", MergePanel,
         "Combine several PDFs into one", keywords="combine join"),
    Tool("split", "Split PDF", ORGANISE, "split", SplitPanel,
         "Break a PDF into separate files", keywords="separate extract pages"),
    Tool("compress", "Compress PDF", OPTIMISE, "compress", CompressPanel,
         "Make the file smaller", keywords="shrink reduce size optimise"),
    Tool("ocr", "OCR · make searchable", OPTIMISE, "scan", OcrPanel,
         "Recognise text in scanned pages", keywords="scan recognise tesseract searchable"),
    Tool("grayscale", "Grayscale PDF", OPTIMISE, "contrast", GrayscalePanel,
         "Remove colour for cheaper printing", keywords="black white gray grey mono"),
    Tool("to_word", "PDF to Word", FROM_PDF, "word", PdfToWordPanel,
         "Editable DOCX with the layout kept", keywords="docx doc word"),
    Tool("to_excel", "PDF to Excel", FROM_PDF, "excel", PdfToExcelPanel,
         "Pull tables into a spreadsheet", keywords="xlsx xls table spreadsheet"),
    Tool("to_powerpoint", "PDF to PowerPoint", FROM_PDF, "powerpoint", PdfToPowerPointPanel,
         "One slide per page", keywords="pptx ppt slides presentation"),
    Tool("to_images", "PDF to Image", FROM_PDF, "img", ToImagesPanel,
         "PNG, JPG, WebP, TIFF or SVG", keywords="png jpg jpeg webp tiff svg picture"),
    Tool("to_text", "PDF to Text & Markdown", FROM_PDF, "txt", PdfToTextPanel,
         "Plain text, Markdown or a web page", keywords="txt md markdown html web"),
    Tool("pdfa", "PDF to PDF/A", FROM_PDF, "pdfa", PdfaPanel,
         "Archive-safe PDF for long-term storage", keywords="archive iso pdfa"),
    Tool("extract", "Extract images", FROM_PDF, "images", ExtractPanel,
         "Save every embedded picture and the text", keywords="pictures photos"),
    Tool("images_to_pdf", "Image to PDF", TO_PDF, "img", ImagesToPdfPanel,
         "JPG, PNG, HEIC, TIFF and more", keywords="jpg png heic photo picture"),
    Tool("office_to_pdf", "Office to PDF", TO_PDF, "word", OfficeToPdfPanel,
         "Word, Excel, PowerPoint and OpenDocument files",
         keywords="docx xlsx pptx odt office word excel powerpoint"),
    Tool("docs_to_pdf", "Web, text & eBook to PDF", TO_PDF, "html", DocsToPdfPanel,
         "HTML, Markdown, TXT, ePub, XPS", keywords="html markdown md txt epub xps ebook"),
    Tool("watermark", "Watermark", EDIT, "droplet", WatermarkPanel,
         "Stamp text or an image on pages", keywords="stamp draft confidential"),
    Tool("page_numbers", "Page numbers", EDIT, "hash", PageNumbersPanel,
         "Number pages anywhere on the page", keywords="numbering footer"),
    Tool("protect", "Protect PDF", SECURE, "lock", ProtectPanel,
         "Encrypt with a password", keywords="encrypt password secure"),
    Tool("unlock", "Unlock PDF", SECURE, "unlock", UnlockPanel,
         "Remove a password you know", keywords="decrypt remove password"),
]

TOOLS_BY_ID = {tool.id: tool for tool in TOOLS}
