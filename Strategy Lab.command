#!/bin/bash
# macOS / Linux: double-click to open Strategy Lab.
# The first run sets up a private Python environment in .venv (takes a few minutes).
cd "$(dirname "$0")" || exit 1
if [ ! -f pyproject.toml ]; then
  echo "This launcher must stay inside the Strategy Lab folder. Unzip the download first, then double-click it there."
  read -r; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Strategy Lab (needs Python 3.11 or newer)..."
  PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
  if [ -z "$PY" ]; then echo "Python 3 not found. Install it from https://www.python.org/downloads/"; read -r; exit 1; fi
  "$PY" -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e ".[desktop]" || { echo "Setup failed (see above)."; read -r; exit 1; }
fi
exec .venv/bin/python -m honestbt.desktop
