"""PyInstaller entry point for PDFSoul.exe (the desktop app)."""

import sys

from pdfsoul.app.main import main

if __name__ == "__main__":
    sys.exit(main())
