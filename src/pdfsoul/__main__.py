"""``python -m pdfsoul`` opens the desktop app; ``python -m pdfsoul merge …`` runs the CLI."""

import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) > 1 and not Path(sys.argv[1]).exists():
        from pdfsoul.cli.main import app

        app()
    else:
        from pdfsoul.app.main import main

        sys.exit(main())
