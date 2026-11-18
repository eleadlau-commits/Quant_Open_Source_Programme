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
    "params": "Settings for the plugin just above. Hover a setting's name to see what it does.",
    "exit": "The exit signal: when to close a trade early (on top of the strategy's own time stop).",
    "costs": "Trading costs taken off every fill: spread, slippage and commission. Cost stress doubles these.",
    "instrument": "Futures contract details: tick size, dollars per point and the account size used for returns.",
    "sweep": "The strategy family: every combination of the listed values is backtested. The tests then judge the "
             "best-looking variant and check whether picking it was just luck.",
    "evaluators": "The tests the best variant has to survive. Each gives PASS, FAIL or N/A in the Verdicts tab.",
    "plugin": "Which plugin does this job. See the Plugin catalogue tab for every choice.",
    "input": "The feature (or mapping) plugged into this mapping.",
    "$map": "Use a mapping's output here: the value is worked out per symbol at decision time.",
    "$feature": "Use a feature's value here, worked out per symbol at decision time.",
    "$suite": "A named group of tests from a test pack, e.g. 'honest-stocks'.",
}

UI = {
    "preset": "Presets are ready-made strategy files to start from: the examples in configs/, strategy families "
              "shipped inside plugin packs (marked with the pack's name), and files you saved (marked 'mine'). "
              "Picking one loads it into the editor; nothing runs until you press Run.",
    "new": "Start a new strategy: pick the trading rules (a strategy plugin) and get a runnable starting point "
           "to build on in the patch bay.",
    "open": "Open a strategy file (.json) from disk.",
    "save": "Save the current settings as your own strategy file. It then appears in Presets as '(mine)'.",
    "plugins": "See every plugin, switch them on or off, and import .tiplug packs.",
    "run": "Backtest every variant in the sweep, then put the best one through the tests (Ctrl+Enter).",
    "patchbay": "The patch bay: build the strategy by wiring boxes. Drag a box to move it, drag from a ● output onto a "
                "setting to plug it in, drag a cable off to unplug it, double-click a setting to type a value, "
                "right-click for everything else. Drag plugins in from the Plugin catalogue.",
    "editor": "The full settings as JSON. Hover any word to see what it means. Changes redraw the patch bay at once.",
    "catalogue": "Every plugin you can use. Double-click one, or drag it onto the patch bay, to put it into your strategy.",
    "summary": "How many tests the best-looking variant survived.",
    "Verdicts": "One block per test. Drag the blocks to arrange them; the order is remembered.",
    "Equity": "Growth of 1 for the selected variant, against the benchmark or ablation when there is one.",
    "Sweep": "Every variant in the family with its results. Click a column to sort.",
    "Trades": "Every trade of the selected variant.",
    "Settings (JSON)": "The full settings as JSON. Hover any word to see what it means.",
    "Plugin catalogue": "Every plugin you can use. Double-click one to add it to your strategy.",
}

KIND_WORDS = {"data": "Data source", "feature": "Feature", "mapping": "Mapping (patch cable)", "signal": "Exit signal",
              "strategy": "Strategy", "evaluator": "Test"}


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
                return f"{KIND_WORDS[kind]} plugin '{word}': {it['doc'].split(chr(10) * 2)[0].strip()}"
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
