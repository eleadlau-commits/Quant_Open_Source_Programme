"""Plain-language explanations shown when you hover over something in the desktop app."""
from __future__ import annotations

from ..registry import catalog

SECTIONS = {
    "name": "The name of this strategy file. Only for you; it doesn't change the backtest.",
    "data": "Where the price bars come from. 'synthetic' makes up stock data (with an optional planted edge), "
            "'synthetic_futures' makes up futures data, 'parquet' reads real bars you downloaded.",
    "features": "Numbers measured for each symbol at decision time, using only data that was already known "
                "(gap, ATR, volatility...). Give each one a short name; the strategy and mappings use that name.",
    "mappings": "Patch cables: small formulas that turn a feature into a setting, e.g. 'exit distance k grows with "
                "volatility'. Use one in the strategy with {\"$map\": \"its name\"}.",
    "strategy": "The trading rules: when to look, what to buy or sell, and how to exit.",
    "params": "Settings for the module just above. Hover a setting's name to see what it does.",
    "exit": "The exit signal: when to close a trade early (on top of the strategy's own time stop).",
    "costs": "Trading costs taken off every fill: spread, slippage and commission. Cost stress doubles these.",
    "instrument": "Futures contract details: tick size, dollars per point and the account size used for returns.",
    "sweep": "The strategy family: every combination of the listed values is backtested. The tests then judge the "
             "best-looking variant and check whether picking it was just luck.",
    "evaluators": "The tests this strategy uses, ticked on the Backtests page. Each gives PASS, FAIL or N/A.",
    "plugin": "Which module does this job. See the module library for every choice.",
    "input": "The feature (or mapping) plugged into this mapping.",
    "$map": "Use a mapping's output here: the value is worked out per symbol at decision time.",
    "$feature": "Use a feature's value here, worked out per symbol at decision time.",
    "$suite": "A named group of tests from a test pack, e.g. 'honest-stocks'.",
}

UI = {
    "Home": "Your strategies, the profit of everything that has run, the settings for every run, how the app "
            "looks, and the library of packs. The only page with things shared by every page.",
    "Data": "The datasets your strategies use, and the global data every strategy can draw on.",
    "Compare": "Strategies next to each other over time. One tab per measure of success; for now, profit.",
    "Backtests": "One list of tests for every strategy. Nothing runs until you ask: double-click one, select a few "
                 "and press Run selected, or press Run all.",
    "patchbay": "The patch bay: build the strategy by wiring boxes. Drag a box to move it, drag from a ● output onto a "
                "setting to plug it in, drag a cable off to unplug it, double-click a setting to type a value, "
                "right-click for everything else. Drag modules in from the module library.",
    "editor": "The full settings as JSON. Hover any word to see what it means. Changes redraw the patch bay at once.",
    "catalogue": "Every module you can use, grouped as Data → Data and Data → Buy/Sell, plus code modules for "
                 "Python strategies. Double-click one, or drag it onto the patch bay, to put it into your strategy.",
    "Trades": "Every trade of the last run. The dots on the chart mark when each one opened.",
    "Settings (JSON)": "The full settings as JSON. Hover any word to see what it means. Changes redraw the patch bay.",
}

KIND_WORDS = {"data": "Data source", "feature": "Feature", "mapping": "Mapping (patch cable)", "signal": "Exit signal",
              "strategy": "Strategy", "evaluator": "Test", "complementary": "Complementary data"}


def _walk_plugins(obj, out: set):
    if isinstance(obj, dict):
        if isinstance(obj.get("plugin"), str):
            out.add(obj["plugin"])
        for v in obj.values():
            _walk_plugins(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_plugins(v, out)
    return out


def plugin_doc(kind: str, name: str) -> str:
    it = next((i for i in catalog().get(kind, []) if i["name"] == name), None)
    return (it or {}).get("doc", "").split("\n\n")[0].strip()


def explain(word: str, cfg: dict | None = None) -> str | None:
    """Explanation for a word in the settings (a section, plugin, setting or name you defined), or None."""
    word = (word or "").strip().strip('"').strip(":").strip(",")
    if not word:
        return None
    cfg = cfg if isinstance(cfg, dict) else {}
    feats, maps = cfg.get("features") or {}, cfg.get("mappings") or {}
    if isinstance(feats, dict) and word in feats and isinstance(feats[word], dict):
        p = feats[word].get("plugin", "?")
        return f"Feature '{word}' = {p}. {plugin_doc('feature', p)}"
    if isinstance(maps, dict) and word in maps and isinstance(maps[word], dict):
        m = maps[word]
        return (f"Mapping (patch cable) '{word}': {m.get('plugin', '?')} of '{m.get('input')}'. "
                f"{plugin_doc('mapping', m.get('plugin', ''))}")
    if word in SECTIONS:
        return SECTIONS[word]
    cat = catalog()
    for kind, items in cat.items():
        for it in items:
            if it["name"] == word:
                return f"{KIND_WORDS[kind]} module '{word}': {it['doc'].split(chr(10) * 2)[0].strip()}"
    used = _walk_plugins(cfg, set())
    hits = [(it["name"] in used, it["name"], p) for items in cat.values() for it in items
            for p in it["params"] if p["name"] == word]
    if hits:
        hits.sort(key=lambda h: not h[0])
        _, owner, p = hits[0]
        default = "" if p["default"] is None else f" Default: {p['default']!r}."
        return f"Setting '{word}' of {owner}: {p['doc']}.{default}".replace("..", ".")
    if "." in word and (cfg.get("sweep") or {}).get(word) is not None:
        return f"Sweep axis: the backtest is repeated for each listed value of {word}."
    from ..plugins import suites

    known = suites()
    if word in known:
        return f"Test suite '{word}': {', '.join(e.get('plugin', '?') for e in known[word])}."
    return None
