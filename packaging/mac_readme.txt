PDFSoul By Billy — offline PDF tools
====================================

INSTALL
1. Drag PDFSoul By Billy onto the Applications folder in this window.
2. Open your Applications folder, RIGHT-CLICK PDFSoul By Billy and choose "Open".
3. Click "Open" again in the warning box.

You only do step 2-3 once. macOS asks because PDFSoul isn't from the App Store.

If macOS says PDFSoul "is damaged" or "can't be opened", open Terminal and run:

    xattr -dr com.apple.quarantine "/Applications/PDFSoul By Billy.app"

then open it normally.

On macOS 15 (Sequoia) and later, right-click → Open may not offer the button. Instead, try to
open PDFSoul once, then go to System Settings → Privacy & Security, scroll down and click
"Open Anyway".


OPTIONAL EXTRAS
Everything works out of the box. Three free helpers unlock a few extra features. With Homebrew
(https://brew.sh) installed, run in Terminal:

    brew install ghostscript tesseract          # best compression, PDF/A, OCR
    brew install --cask libreoffice             # exact-layout Word/Excel/PowerPoint → PDF

PDFSoul finds them automatically.

Your files never leave your computer: PDFSoul makes no network connections.
