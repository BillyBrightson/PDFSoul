"""Light and dark themes. "System" follows the operating system setting, live."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from pdfsoul.app import icons

ACCENT = "#6d4aff"
ACCENT_DARK = "#9a82ff"
MODES = ("system", "light", "dark")

_mode = "system"


@dataclass(frozen=True)
class Tokens:
    bg: str  # behind everything
    surface: str  # sidebar, panes, cards
    raised: str  # inputs, buttons
    hover: str
    line: str
    text: str
    muted: str
    accent: str
    accent_soft: str
    canvas: str  # behind the pages in the viewer
    success: str
    danger: str


LIGHT = Tokens(bg="#f4f5f8", surface="#ffffff", raised="#ffffff", hover="#f1f0fb",
               line="#e3e4ea", text="#17181d", muted="#6b6f7e", accent=ACCENT,
               accent_soft="rgba(109, 74, 255, 0.10)", canvas="#e9eaef", success="#15803d",
               danger="#d43c3c")
DARK = Tokens(bg="#0c0c0d", surface="#121214", raised="#1a1a1d", hover="#1e1e22",
              line="#26262b", text="#f4f4f5", muted="#a1a1aa", accent=ACCENT_DARK,
              accent_soft="rgba(154, 130, 255, 0.16)", canvas="#060607", success="#4ade80",
              danger="#f87171")


def set_mode(mode: str) -> None:
    global _mode
    _mode = mode if mode in MODES else "system"


def is_dark() -> bool:
    if _mode == "system":
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return _mode == "dark"


def tokens() -> Tokens:
    return DARK if is_dark() else LIGHT


def accent() -> QColor:
    return QColor(tokens().accent)


def _palette(t: Tokens) -> QPalette:
    p = QPalette()
    colors = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.raised,
        QPalette.ColorRole.AlternateBase: t.bg,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.raised,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.ToolTipBase: t.surface,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.muted,
        QPalette.ColorRole.Mid: t.line,
        QPalette.ColorRole.Dark: t.line,
        QPalette.ColorRole.Light: t.surface,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: t.accent,
    }
    for role, value in colors.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted))
    return p


def _asset(name: str, color: str) -> str:
    """Write a tinted icon to a temp file so the stylesheet can use it as an image."""
    folder = Path(tempfile.gettempdir()) / "pdfsoul-theme"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_text(icons.svg(name, color, 2.2), encoding="utf-8")
    return path.as_posix()


def _rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _stylesheet(t: Tokens, dark: bool) -> str:
    down = _asset("chevron-down", t.muted)
    up = _asset("chevron-up", t.muted)
    check = _asset("check", "#ffffff")
    dot = _asset("dot", "#ffffff")
    accent_hover = QColor(t.accent).lighter(110 if not dark else 115).name()
    accent_press = QColor(t.accent).darker(110).name()
    return f"""
    QMainWindow, QDialog {{ background: {t.bg}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.line};
               border-radius: 6px; padding: 5px 8px; }}

    /* --- chrome ---------------------------------------------------------------------- */
    QWidget#Sidebar {{ background: {t.surface}; border-right: 1px solid {t.line}; }}
    QWidget#OptionsPane {{ background: {t.surface}; border-left: 1px solid {t.line}; }}
    QWidget#OptionsPane QScrollArea, QWidget#OptionsPane QScrollArea > QWidget > QWidget
        {{ background: {t.surface}; }}
    QLabel#Brand {{ font-size: 16px; font-weight: 700; }}
    QLabel#BrandSub {{ color: {t.muted}; font-size: 11px; }}
    QTreeWidget#ToolList {{ border: none; background: transparent; outline: 0; }}
    QTreeWidget#ToolList::item {{ padding: 4px 6px; margin: 0; border-radius: 7px;
                                  color: {t.muted}; }}
    QTreeWidget#ToolList::item:hover {{ background: {t.hover}; color: {t.text}; }}
    QTreeWidget#ToolList::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
    QPushButton#SidebarButton {{ text-align: left; padding: 7px 10px; border: none;
                                 border-radius: 7px; background: transparent; }}
    QPushButton#SidebarButton:hover {{ background: {t.hover}; }}
    QSplitter::handle {{ background: {t.line}; }}
    QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.line}; color: {t.muted}; }}
    QStatusBar QLabel {{ color: {t.muted}; padding: 0 6px; }}
    QStatusBar::item {{ border: none; }}

    QToolBar {{ background: {t.surface}; border: none; border-bottom: 1px solid {t.line};
               padding: 5px 8px; spacing: 3px; }}
    QToolBar::separator {{ background: {t.line}; width: 1px; margin: 6px 6px; }}
    QToolButton {{ border: 1px solid transparent; border-radius: 7px; padding: 5px;
                  color: {t.text}; background: transparent; }}
    QToolButton:hover {{ background: {t.hover}; }}
    QToolButton:pressed {{ background: {t.accent_soft}; }}
    QToolButton:checked {{ background: {t.accent_soft}; color: {t.accent}; }}
    QToolButton:disabled {{ color: {t.muted}; }}
    QLabel#DocTitle {{ font-weight: 600; padding: 0 4px; }}
    QLabel#DocMeta {{ color: {t.muted}; }}
    QWidget#SearchBar {{ background: {t.surface}; border-bottom: 1px solid {t.line}; }}

    QMenuBar {{ background: {t.surface}; border-bottom: 1px solid {t.line}; }}
    QMenuBar::item {{ padding: 4px 9px; border-radius: 5px; background: transparent; }}
    QMenuBar::item:selected {{ background: {t.hover}; }}
    QMenu {{ background: {t.surface}; border: 1px solid {t.line}; border-radius: 8px;
            padding: 5px; }}
    QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
    QMenu::item:disabled {{ color: {t.muted}; }}
    QMenu::separator {{ height: 1px; background: {t.line}; margin: 4px 6px; }}

    /* --- controls -------------------------------------------------------------------- */
    QPushButton {{ background: {t.raised}; border: 1px solid {t.line}; border-radius: 8px;
                  padding: 6px 13px; color: {t.text}; }}
    QPushButton:hover {{ background: {t.hover};
                        border-color: {QColor(t.line).darker(112).name()}; }}
    QPushButton:pressed {{ background: {t.accent_soft}; }}
    QPushButton:disabled {{ color: {t.muted}; background: {t.bg}; }}
    QPushButton:flat {{ border: none; background: transparent; }}
    QPushButton:flat:hover {{ background: {t.hover}; }}
    QPushButton#Primary {{ background: {t.accent}; color: white; border: none;
                          border-radius: 9px; padding: 10px 18px; font-weight: 600;
                          font-size: 14px; }}
    QPushButton#Primary:hover {{ background: {accent_hover}; }}
    QPushButton#Primary:pressed {{ background: {accent_press}; }}
    QPushButton#Primary:disabled {{ background: {t.line}; color: {t.muted}; }}
    QPushButton#Link {{ border: none; background: transparent; color: {t.accent};
                       padding: 2px 4px; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}
    QPushButton#Credit {{ border: none; background: transparent; color: {t.muted};
                         font-size: 12px; padding: 4px 8px; }}
    QPushButton#Credit:hover {{ color: {t.text}; }}

    /* --- about ----------------------------------------------------------------------- */
    QLabel#AboutName {{ font-size: 24px; font-weight: 700; }}
    QLabel#AboutMuted {{ color: {t.muted}; font-size: 12px; }}
    QLabel#AboutLove {{ font-size: 14px; }}
    QLabel#AboutPill {{ background: {t.accent_soft}; color: {t.accent}; font-size: 11px;
                       font-weight: 700; letter-spacing: 1px; border-radius: 11px;
                       padding: 5px 12px; }}
    QFrame#AboutTile {{ background: {t.raised}; border: 1px solid {t.line};
                       border-radius: 10px; }}
    QLabel#AboutStat {{ font-size: 18px; font-weight: 700; }}
    QLabel#AboutQuote {{ color: {t.muted}; font-style: italic; font-size: 13px; }}
    QLabel#AboutSmall {{ color: {t.muted}; font-size: 11px; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background: {t.raised}; border: 1px solid {t.line}; border-radius: 7px;
        padding: 5px 8px; color: {t.text}; selection-background-color: {t.accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QPlainTextEdit:focus {{ border-color: {t.accent}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled
        {{ color: {t.muted}; background: {t.bg}; }}
    QComboBox {{ padding-right: 24px; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.line};
                                   border-radius: 6px; padding: 4px; outline: 0;
                                   selection-background-color: {t.accent_soft};
                                   selection-color: {t.text}; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border;
        subcontrol-position: top right; width: 18px; border: none; background: transparent; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
        subcontrol-position: bottom right; width: 18px; border: none; background: transparent; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 9px;
                                                   height: 9px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 9px;
                                                       height: 9px; }}
    QSpinBox[buttonSymbols="2"] {{ padding-right: 8px; }}

    QCheckBox, QRadioButton {{ spacing: 8px; padding: 2px 0; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px;
                           border: 1px solid {_rgba(t.muted, 0.55)}; background: {t.raised}; }}
    QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
                                   image: url("{check}"); }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px;
                              border: 1px solid {_rgba(t.muted, 0.55)}; background: {t.raised}; }}
    QRadioButton::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
                                      image: url("{dot}"); }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.line}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: white; border: 1px solid {t.line};
                                 width: 16px; height: 16px; margin: -7px 0;
                                 border-radius: 8px; }}
    QProgressBar {{ background: {t.line}; border: none; border-radius: 3px; height: 6px; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {_rgba(t.muted, 0.35)}; border-radius: 3px;
                                  min-height: 32px; margin: 0 2px; }}
    QScrollBar::handle:horizontal {{ background: {_rgba(t.muted, 0.35)};
                                    border-radius: 3px; min-width: 32px; margin: 2px 0; }}
    QScrollBar::handle:hover {{ background: {_rgba(t.muted, 0.6)}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QGroupBox {{ border: 1px solid {t.line}; border-radius: 10px; margin-top: 14px;
                padding: 14px 10px 10px 10px; background: {t.surface}; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px;
                       font-weight: 600; }}
    QTreeWidget, QListWidget {{ background: {t.raised}; border: 1px solid {t.line};
                               border-radius: 8px; alternate-background-color: {t.bg}; }}
    QTreeWidget::item, QListWidget::item {{ padding: 4px 2px; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {t.accent_soft};
                                                             color: {t.text}; }}
    QHeaderView::section {{ background: {t.bg}; border: none;
                           border-bottom: 1px solid {t.line}; padding: 5px 8px;
                           color: {t.muted}; font-weight: 600; }}

    /* --- tool panels ----------------------------------------------------------------- */
    QLabel#PanelTitle {{ font-size: 18px; font-weight: 700; }}
    QLabel#PanelGroup {{ color: {t.muted}; font-size: 11px; font-weight: 600; }}
    QLabel#Muted, QLabel#Hint {{ color: {t.muted}; }}
    QLabel#Section {{ color: {t.muted}; font-size: 11px; font-weight: 700;
                     letter-spacing: 0.6px; }}
    QLabel#Note {{ background: {t.accent_soft}; border-radius: 8px; padding: 8px 10px; }}
    QLabel#Warn {{ background: rgba(234, 88, 12, 0.12); border-radius: 8px;
                  padding: 8px 10px; }}
    QFrame#ResultCard {{ border: 1px solid {t.line}; border-radius: 10px;
                        background: {t.bg}; }}
    QFrame#ResultCard[error="false"] {{ border-color: {t.success}; }}
    QFrame#ResultCard[error="true"] {{ border-color: {t.danger}; }}
    QFrame#EmptyState {{ border: 1px dashed {t.line}; border-radius: 12px; }}

    /* --- home ------------------------------------------------------------------------ */
    QWidget#HomeBody, QScrollArea#Home {{ background: {t.bg}; }}
    QLabel#HomeTitle {{ font-size: 26px; font-weight: 800; }}
    QLabel#HomeSub {{ color: {t.muted}; font-size: 14px; }}
    QLineEdit#HomeSearch {{ padding: 8px 10px; border-radius: 10px; font-size: 14px;
                           background: {t.surface}; }}
    QFrame#DropZone {{ border: 1.5px dashed {_rgba(t.accent, 0.55)}; border-radius: 16px;
                      background: {t.surface}; }}
    QFrame#DropZone[dragging="true"] {{ background: {t.hover}; border-color: {t.accent}; }}
    QLabel#DropTitle {{ font-size: 17px; font-weight: 700; }}
    QLabel#ColumnTitle {{ font-size: 17px; font-weight: 700; color: {t.text};
                         padding: 0 0 4px 2px; }}
    QPushButton#ToolRow {{ text-align: left; border: none; background: transparent;
                          color: {t.muted}; font-size: 15px; padding: 8px 10px;
                          border-radius: 8px; }}
    QPushButton#ToolRow:hover {{ color: {t.text}; background: {t.hover}; }}
    QPushButton#ToolRow:pressed {{ background: {t.accent_soft}; }}
    QLabel#NoMatch {{ color: {t.muted}; font-size: 14px; padding: 16px 2px; }}
    QFrame#RecentCard {{ background: {t.surface}; border: 1px solid {t.line};
                        border-radius: 10px; }}
    QFrame#RecentCard:hover {{ border-color: {t.accent}; }}

    QAbstractScrollArea#PageView {{ background: {t.canvas}; border: none; }}
    QListView#Organiser {{ background: {t.canvas}; border: none; }}
    QListView#ThumbStrip {{ background: {t.surface}; border: none;
                           border-right: 1px solid {t.line}; }}
    QListView#ThumbStrip::item, QListView#Organiser::item {{ border-radius: 8px;
                                                             padding: 4px; }}
    QListView#ThumbStrip::item:selected, QListView#Organiser::item:selected {{
        background: {t.accent_soft}; color: {t.text}; }}
    QListView#ThumbStrip::item:hover, QListView#Organiser::item:hover {{
        background: {t.hover}; }}
    """


def apply_theme(app: QApplication, mode: str | None = None) -> None:
    if mode is not None:
        set_mode(mode)
    app.setStyle("Fusion")
    t, dark = tokens(), is_dark()
    app.setPalette(_palette(t))
    app.setStyleSheet(_stylesheet(t, dark))


def follow_system_theme(app: QApplication, mode: str = "system") -> None:
    apply_theme(app, mode)

    def changed(_: object) -> None:
        if _mode == "system":
            apply_theme(app)

    QGuiApplication.styleHints().colorSchemeChanged.connect(changed)
