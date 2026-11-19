"""Code modules: small functions you can drop into a strategy written in Python.

They are plain .py files in Documents/Titanium/modules, one function per file,
so you can add your own. The starter set is imported from the Starters window.
Data → Data modules take F (all data up to now) and return a number or None;
Data → Buy/Sell modules return positions. The kind is read from the docstring
("Data -> Buy/Sell: ..."), otherwise Data → Data.
"""
from __future__ import annotations

import ast
from pathlib import Path


def load_code_modules(folder: Path) -> dict[str, tuple[str, str, str]]:
    """{function name: (kind, one-line description, code)} for every module file in ``folder``."""
    out: dict[str, tuple[str, str, str]] = {}
    for f in sorted(folder.glob("*.py")) if folder.is_dir() else []:
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef)), None)
        if fn is None:
            continue
        doc = (ast.get_docstring(fn) or "").strip().split("\n")[0]
        kind = "Data → Buy/Sell" if "buy/sell" in doc.lower().split(":")[0] else "Data → Data"
        if ":" in doc and doc.split(":")[0].lower().startswith("data"):
            doc = doc.split(":", 1)[1].strip()
        out[fn.name] = (kind, doc, src)
    return out
