"""Build a static copy of the web UI that runs honestbt in the browser (Pyodide).

    python scripts/build_static_site.py --out _site
    python -m http.server -d _site 8000     # try it locally

The GitHub Actions workflow `.github/workflows/pages.yml` runs this and
publishes `_site` to GitHub Pages.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for f in (ROOT / "web").iterdir():
        if f.is_file():
            shutil.copy(f, out / f.name)
    html = (out / "index.html").read_text()
    html = html.replace('href="/static/', 'href="./').replace('src="/static/', 'src="./')
    html = html.replace('<script src="./app.js"></script>',
                        '<script>window.HONESTBT_STATIC = true;</script>\n'
                        '  <script src="./pyodide-backend.js"></script>\n'
                        '  <script src="./app.js"></script>')
    (out / "index.html").write_text(html)

    files = []
    for f in sorted((ROOT / "honestbt").rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if rel == "honestbt/api.py":  # needs FastAPI, not used in the browser
            continue
        dest = out / "py" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, dest)
        files.append(rel)
    (out / "configs").mkdir()
    configs = []
    for f in sorted((ROOT / "configs").glob("*.json")):
        shutil.copy(f, out / "configs" / f.name)
        configs.append(f.stem)
    (out / "py-manifest.json").write_text(json.dumps({"files": files, "configs": configs}, indent=1))
    (out / ".nojekyll").write_text("")
    print(f"built {out} with {len(files)} python files, {len(configs)} configs")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    build(Path(ap.parse_args().out))
