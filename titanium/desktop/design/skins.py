"""Skin packs: swappable looks for the whole app.

A skin is a TOML file (see ``packs/classic.toml`` for every key) with a light and a
dark palette, shape, fonts, effects and optional extra QSS. ``extends = "<id>"``
inherits everything the file leaves out, so a skin can be a handful of lines.

Skins come from three places, in this order: the built-in ``packs`` folder next to this file,
plugins (``Library.SKINS``) and the user's skins folder (``Documents/Titanium/skins``).
A broken skin never stops the app: it is skipped, the reason is kept in
:func:`problems`, and asking for it gives the default skin.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any

from . import tokens as T

BUILTIN_DIR = Path(__file__).resolve().parent / "packs"
DEFAULT = "graphite"

_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_PALETTE_KEYS = [f.name for f in fields(T.Palette) if f.name != "name"]
_EFFECT_FIELDS = {f.name: f for f in fields(T.Effects)}
_CHOICES = {"canvas": {"none", "dots", "lines"}, "nav_marker": {"tile", "dot"},
            "primary": {"fill", "edge"}, "run": {"fill", "capsule"}, "numbers": {"ui", "mono"}}
_RADII = ("sm", "md", "lg", "xl")

_skins: dict[str, T.Skin] = {}
_raw: dict[str, dict] = {}  # merged data, so later skins can extend earlier ones
_problems: list[str] = []


class SkinError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _palette(name: str, data: dict, where: str) -> T.Palette:
    unknown = set(data) - set(_PALETTE_KEYS)
    if unknown:
        raise SkinError(f"{where}: unknown colour names {sorted(unknown)}")
    missing = [k for k in _PALETTE_KEYS if k not in data]
    if missing:
        raise SkinError(f"{where}: missing colours {missing}")
    values: dict[str, Any] = {}
    for k in _PALETTE_KEYS:
        v = data[k]
        items = v if k == "series" else [v]
        if k == "series" and (not isinstance(v, list) or not v):
            raise SkinError(f"{where}: series must be a list of colours")
        for c in items:
            if not isinstance(c, str) or not _COLOUR.match(c):
                raise SkinError(f"{where}: {k} = {c!r} is not a #rrggbb or #rrggbbaa colour")
        values[k] = tuple(v) if k == "series" else v
    return T.Palette(name=name, **values)


def _effects(data: dict, where: str) -> T.Effects:
    unknown = set(data) - set(_EFFECT_FIELDS)
    if unknown:
        raise SkinError(f"{where}: unknown effects {sorted(unknown)}")
    for k, choices in _CHOICES.items():
        if k in data and data[k] not in choices:
            raise SkinError(f"{where}: effects.{k} must be one of {sorted(choices)}")
    if "glow" in data:
        data = dict(data, glow=max(0.0, min(1.0, float(data["glow"]))))
    for k in ("panel_gradient", "top_highlight"):
        if k in data and not isinstance(data[k], bool):
            raise SkinError(f"{where}: effects.{k} must be true or false")
    return T.Effects(**data)


def parse(data: dict, source: str = "") -> T.Skin:
    """Build a Skin from TOML data (after ``extends`` is resolved against loaded skins)."""
    where = source or data.get("id", "skin")
    sid = data.get("id")
    if not isinstance(sid, str) or not re.match(r"^[a-z0-9][a-z0-9_-]*$", sid):
        raise SkinError(f"{where}: id must be lower-case letters, digits, - or _")
    parent = data.get("extends")
    if parent:
        if parent not in _raw:
            raise SkinError(f"{where}: extends {parent!r}, which isn't loaded")
        base = {k: v for k, v in _raw[parent].items() if k not in ("id", "name", "description", "extends", "qss")}
        data = _merge(base, data)
    radius = data.get("shape", {}).get("radius", {})
    if sorted(radius) != sorted(_RADII) or not all(isinstance(radius[k], int) and 0 <= radius[k] <= 24 for k in _RADII):
        raise SkinError(f"{where}: shape.radius needs whole numbers 0-24 for {list(_RADII)}")
    fonts = data.get("fonts", {})
    skin = T.Skin(
        id=sid,
        name=str(data.get("name", sid)),
        description=str(data.get("description", "")),
        light=_palette("light", data.get("light", {}), f"{where} [light]"),
        dark=_palette("dark", data.get("dark", {}), f"{where} [dark]"),
        radius=dict(radius),
        ui_fonts=tuple(fonts.get("ui") or T.FONT_FAMILIES),
        mono_fonts=tuple(fonts.get("mono") or T.MONO_FAMILIES),
        effects=_effects(data.get("effects", {}), where),
        qss=str(data.get("qss", "")),
        source=source,
    )
    _raw[sid] = data
    return skin


def register(skin: T.Skin | dict | str | Path, source: str = "") -> T.Skin | None:
    """Add a skin (a Skin, TOML data, or a path to a .toml file). Returns None and
    records the reason if it is broken."""
    where = source
    try:
        if isinstance(skin, (str, Path)):
            path = Path(skin)
            where = source or str(path)
            skin = tomllib.loads(path.read_text(encoding="utf-8"))
        if isinstance(skin, dict):
            skin = parse(skin, source)
        if not isinstance(skin, T.Skin):
            raise SkinError("not a skin")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, SkinError, TypeError, ValueError) as e:
        _problems.append(f"Skipped skin {where}: {e}")
        return None
    if skin.id in _skins and _skins[skin.id].source == "" and skin.source:
        _problems.append(f"Skipped skin {skin.source}: id {skin.id!r} is a built-in skin")
        return None
    _skins[skin.id] = skin
    return skin


def load_folder(folder: str | Path) -> list[T.Skin]:
    """Load every ``*.toml`` in a folder (missing folder: nothing). Parents load first."""
    folder = Path(folder)
    if folder != BUILTIN_DIR:
        _ensure_builtin()
    if not folder.is_dir():
        return []
    pending = sorted(folder.glob("*.toml"))
    loaded: list[T.Skin] = []
    # a file may extend another file in the same folder: retry until no progress
    while pending:
        progress, waiting = False, []
        for path in pending:
            try:
                parent = tomllib.loads(path.read_text(encoding="utf-8")).get("extends")
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
                parent = None
            if parent and parent not in _raw and any(p.stem == parent for p in pending if p != path):
                waiting.append(path)
                continue
            s = register(path, "" if folder == BUILTIN_DIR else str(path))
            if s is not None:
                loaded.append(s)
            progress = True
        if not progress:
            for path in waiting:
                register(path, str(path))
            break
        pending = waiting
    return loaded


def load_plugin_entries(entries) -> None:
    """Register the skins plugins added to ``Library.SKINS`` (Skin, dict or path)."""
    _ensure_builtin()
    for e in entries:
        register(e.obj, f"plugin {e.plugin or 'app'}: {e.name}")


def get(skin_id: str | None) -> T.Skin:
    """The skin with that id, or the default skin if there is none."""
    _ensure_builtin()
    if skin_id in _skins:
        return _skins[skin_id]
    if skin_id:
        _problems.append(f"No skin called {skin_id!r}; using {DEFAULT}.")
    return _skins[DEFAULT]


def available() -> list[T.Skin]:
    _ensure_builtin()
    builtin = sorted((s for s in _skins.values() if not s.source), key=lambda s: (s.id != DEFAULT, s.name))
    others = sorted((s for s in _skins.values() if s.source), key=lambda s: s.name)
    return builtin + others


def problems() -> list[str]:
    return list(_problems)


def _ensure_builtin() -> None:
    if "classic" not in _skins:
        load_folder(BUILTIN_DIR)
        if DEFAULT not in _skins or "classic" not in _skins:
            raise RuntimeError("built-in skins failed to load: " + "; ".join(_problems))


def reset() -> None:
    """Forget every skin and problem (tests)."""
    _skins.clear()
    _raw.clear()
    _problems.clear()
