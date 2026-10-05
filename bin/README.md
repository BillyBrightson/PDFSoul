# bin/

External engines bundled into the installer. `packaging/build_windows.ps1` copies them in;
they are not committed.

| File | Engine | Used by |
| --- | --- | --- |
| `gswin64c.exe`, `gsdll64.dll` | Ghostscript | Compress |
| `tesseract/` + `tessdata/eng.traineddata` | Tesseract | OCR (v2) |

At runtime `pdfsoul.core.engines` looks here first, then at a path set in Settings, `PATH`,
and the usual install folders. LibreOffice is detected, never bundled.
