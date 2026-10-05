"""PyInstaller entry point for the command line (shipped as pdfsoul.com)."""

from pdfsoul.cli.main import app

if __name__ == "__main__":
    app(prog_name="pdfsoul")
