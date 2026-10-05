"""PDFSoul's engine: plain functions with no Qt imports, shared by the UI, the CLI and tests.

Modules:
    organise  merge, split, rotate, reorder, delete, duplicate, insert blank, extract pages
    pagelist  editable page plan with undo/redo (the organiser grid's model)
    convert   images ↔ PDF, extract text and images
    edit      watermarks and page numbers
    secure    encrypt, decrypt, permissions
    optimise  compress, repair
    engines   locate and run Ghostscript / Tesseract / LibreOffice
    document  open (with passwords and auto-repair) and save safely
    safe_io   temp file + atomic rename, output naming
"""
