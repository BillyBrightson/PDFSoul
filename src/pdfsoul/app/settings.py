"""User settings, stored with QSettings (the registry on Windows). Passwords are never stored."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from pdfsoul.core import engines
from pdfsoul.core.optimise import CompressPreset
from pdfsoul.core.safe_io import derive_output, unique_path

MAX_RECENT = 10
ENGINE_NAMES = ("gs", "tesseract", "soffice")


class Settings:
    def __init__(self, store: QSettings | None = None) -> None:
        self._s = store or QSettings()
        self.apply_engine_overrides()

    # -- output --------------------------------------------------------------------------------

    @property
    def output_folder(self) -> str:
        """Blank means 'next to the source file'."""
        return str(self._s.value("output/folder", ""))

    @output_folder.setter
    def output_folder(self, value: str) -> None:
        self._s.setValue("output/folder", value)

    @property
    def replace_existing(self) -> bool:
        """If an output name is taken: replace it (True) or add (2), (3)… (False, default)."""
        return self._s.value("output/replace_existing", False, type=bool)

    @replace_existing.setter
    def replace_existing(self, value: bool) -> None:
        self._s.setValue("output/replace_existing", value)

    @property
    def save_overwrites_original(self) -> bool:
        """Ctrl+S writes over the open file instead of saving a copy. Off by default."""
        return self._s.value("output/save_overwrites_original", False, type=bool)

    @save_overwrites_original.setter
    def save_overwrites_original(self, value: bool) -> None:
        self._s.setValue("output/save_overwrites_original", value)

    def output_for(self, source: Path, tag: str, ext: str = ".pdf") -> Path:
        folder = Path(self.output_folder) if self.output_folder else None
        path = derive_output(source, tag, ext, folder)
        return path if self.replace_existing else unique_path(path)

    def folder_for(self, source: Path, tag: str) -> Path:
        base = Path(self.output_folder) if self.output_folder else source.parent
        path = base / f"{source.stem}_{tag}"
        return path if self.replace_existing else unique_path(path)

    # -- tools ---------------------------------------------------------------------------------

    @property
    def compress_preset(self) -> CompressPreset:
        value = str(self._s.value("tools/compress_preset", CompressPreset.MEDIUM.value))
        try:
            return CompressPreset(value)
        except ValueError:
            return CompressPreset.MEDIUM

    @compress_preset.setter
    def compress_preset(self, value: CompressPreset) -> None:
        self._s.setValue("tools/compress_preset", CompressPreset(value).value)

    # -- appearance ----------------------------------------------------------------------------

    @property
    def theme(self) -> str:
        """"system", "light" or "dark"."""
        value = str(self._s.value("view/theme", "system"))
        return value if value in {"system", "light", "dark"} else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        self._s.setValue("view/theme", value)

    # -- engines -------------------------------------------------------------------------------

    def engine_path(self, name: str) -> str:
        return str(self._s.value(f"engines/{name}", ""))

    def set_engine_path(self, name: str, path: str) -> None:
        self._s.setValue(f"engines/{name}", path)
        engines.set_override(name, path or None)

    def apply_engine_overrides(self) -> None:
        for name in ENGINE_NAMES:
            engines.set_override(name, self.engine_path(name) or None)

    # -- recent files --------------------------------------------------------------------------

    @property
    def recent_files(self) -> list[Path]:
        raw = self._s.value("recent/files", [])
        items = [raw] if isinstance(raw, str) else list(raw or [])
        return [Path(p) for p in items if p]

    def add_recent(self, path: Path) -> None:
        path = Path(path).resolve()
        items = [p for p in self.recent_files if p != path]
        self._s.setValue("recent/files", [str(p) for p in [path, *items][:MAX_RECENT]])

    def remove_recent(self, path: Path) -> None:
        self._s.setValue("recent/files",
                         [str(p) for p in self.recent_files if p != Path(path)])

    def clear_recent(self) -> None:
        self._s.setValue("recent/files", [])

    # -- window --------------------------------------------------------------------------------

    def value(self, key: str, default: object = None) -> object:
        return self._s.value(key, default)

    def set_value(self, key: str, value: object) -> None:
        self._s.setValue(key, value)
