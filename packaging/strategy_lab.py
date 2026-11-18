"""Entry script for the PyInstaller build (absolute import, no package context)."""
import sys

from honestbt.desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
