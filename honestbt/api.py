"""Minimal HTTP API + static web UI.

    uvicorn honestbt.api:app --reload      # then open http://127.0.0.1:8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .patchbay import ConfigError, validate
from .registry import catalog, load_plugins
from .runner import run_config

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CONFIGS = ROOT / "configs"

load_plugins()
app = FastAPI(title="honestbt", version="0.1.0")


@app.get("/api/plugins")
def plugins():
    return catalog()


@app.get("/api/configs")
def configs():
    return sorted(p.stem for p in CONFIGS.glob("*.json"))


@app.get("/api/configs/{name}")
def config(name: str):
    path = (CONFIGS / f"{name}.json").resolve()
    if path.parent != CONFIGS.resolve() or not path.exists():
        raise HTTPException(404, "no such config")
    return json.loads(path.read_text())


@app.post("/api/validate")
def validate_config(cfg: dict = Body(...)):
    load_plugins()
    return {"problems": validate(cfg)}


@app.post("/api/run")
def run(cfg: dict = Body(...)):
    try:
        return run_config(cfg)
    except (ConfigError, KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
