"""The workspace: datasets, strategies and runs open in this session.

Runs are kept in memory for the session only (Compare and Backtests read them here).
Datasets and strategies are saved by their own sections.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..core.default_strategy import is_default
from ..core.markets import MARKETS, Market, MarketDefaults
from ..core.measurements import register_measurements
from ..core.module_library import load_library_folder
from ..core.plugins import Library, Registry
from ..core.strategy import StrategyGraph
from .backtests import BacktestResult, BacktestService
from .collection import Collection
from .events import Event
from .datasets import DatasetService
from .plugins import PluginManager
from .runs import RunJob, RunService
from .settings import RunDefaults
from .module_folders import ModuleFolders

__all__ = ["BacktestResult", "BacktestService", "Collection", "DatasetService", "ModuleFolders", "RunDefaults", "RunJob",
           "StrategyFootprint",
           "RunService", "Workspace"]


@dataclass(frozen=True)
class StrategyFootprint:
    """What deleting a strategy takes with it."""
    runs: int
    backtests: int
    running: int  # runs and tests of it still going (deleting cancels them)


_NUMBERED = re.compile(r"Strategy (\d+)")


class Workspace:
    """``data_root``: the folder datasets are saved in. Without one (tests, scripts) they
    live in a temporary folder for the session. The app passes ``paths.app_folder() / "data"``.

    ``plugins_folder``: the user's plugins (and where on/off is remembered). Without one,
    only the built-in plugins load, and on/off lasts for the session. ``library_folder``:
    the module library folder on disk (``<folder>/<module>.py``); None adds nothing.
    """

    def __init__(self, registry: Registry | None = None, data_root: Path | str | None = None,
                 plugins_folder: Path | str | None = None, library_folder: Path | str | None = None,
                 run_defaults: RunDefaults | None = None) -> None:
        self.registry = registry if registry is not None else Registry()
        register_measurements(self.registry)  # part of the app, not a plugin; plugins add more
        self.plugins = PluginManager(self.registry, user_folder=plugins_folder)
        self.plugins.load()
        self.library_folder: Path | None = Path(library_folder) if library_folder is not None else None
        self.library_problems: list[str] = []
        self.library_changed = Event()  # ()
        self.reload_library()
        self.modules = ModuleFolders(self)  # make and change folders and modules in the library folder
        self.run_defaults = run_defaults or RunDefaults()
        self.run_defaults_changed = Event()  # (RunDefaults,)
        self.datasets = DatasetService(self.registry, data_root)
        self.strategies: Collection[StrategyGraph] = Collection()
        self.runs = RunService(self.datasets, self.strategies)
        self.market_defaults: dict[str, MarketDefaults] = {}  # the app's edits, by market id
        self.market_defaults_changed = Event()  # (market_id, MarketDefaults)
        self.runs.defaults = lambda ds: self.run_settings(dataset_id=ds)
        self.backtests = BacktestService(self.registry, self.runs, self.strategies)
        self.strategies.added.connect(self._strategy_changed)
        self.strategies.changed.connect(self._strategy_changed)
        self.strategies.removed.connect(lambda sid: self.datasets.sync_strategy(sid, []))  # closed: frees its data
        self.focused_strategy: str | None = None  # the strategy whose tab is in front
        self.strategy_focused = Event()  # (id or None,)

    # ---- the backtest worker process ------------------------------------------------
    def backtest_worker(self, start: bool = True):
        """The process backtests run in (``app/backtest_worker.py``), started on first use and
        kept for the session; ``None`` if it can't be started here (then they run on a thread)."""
        w = getattr(self, "_worker", None)
        if w is None:
            from .backtest_worker import BacktestWorker

            w = self._worker = BacktestWorker({
                "data_root": str(self.datasets.root),
                "plugins_folder": str(self.plugins.user_folder) if self.plugins.user_folder else None,
                "off": sorted(self.plugins.switched_off())})
        if start and not w.alive:
            try:
                w.start()
            except Exception as e:  # noqa: BLE001 - some machines don't let an app start a copy of itself
                w.problem = f"couldn't start the backtest worker ({type(e).__name__}: {e})"
                return None
        return w

    def stop_backtest_worker(self) -> None:
        w = getattr(self, "_worker", None)
        if w is not None:
            w.stop()

    # ---- settings the engine and the library read ------------------------------------
    def set_run_defaults(self, defaults: RunDefaults) -> None:
        if defaults != self.run_defaults:
            self.run_defaults = defaults
            self.run_defaults_changed.emit(defaults)

    def run_settings(self, *layers: dict | None, market: str | None = None, dataset_id: str | None = None) -> dict:
        """The settings a run starts with: the run defaults, then the market's defaults (the
        ``market`` given, or ``dataset_id``'s), then each layer (strategy, run)."""
        if market is None and dataset_id is not None and dataset_id in self.datasets:
            market = self.datasets.get(dataset_id).market
        known = self.markets()
        base = known[market].defaults.settings() if market in known else {}
        return self.run_defaults.apply(base, *layers)

    # ---- markets: built in, or added by plugins; the app can edit their defaults -------
    def markets(self, edited: bool = True) -> dict[str, Market]:
        """Every market by id, with the app's edits to its defaults (``edited=False``: as the market ships)."""
        out = dict(MARKETS)
        for entry in self.registry.entries(Library.MARKETS):
            if isinstance(entry.obj, Market):
                out.setdefault(entry.obj.id, entry.obj)
        if not edited:
            return out
        return {mid: m.with_defaults(self.market_defaults[mid]) if mid in self.market_defaults else m
                for mid, m in out.items()}

    def market(self, market_id: str) -> Market:
        try:
            return self.markets()[market_id]
        except KeyError:
            raise KeyError(f"no market {market_id!r} (known: {', '.join(self.markets())})") from None

    def set_market_defaults(self, market_id: str, defaults: MarketDefaults | None) -> None:
        """Change a market's defaults for every run from now on; ``None`` goes back to the market's own."""
        before = self.market(market_id).defaults
        if defaults is None:
            self.market_defaults.pop(market_id, None)
        else:
            self.market_defaults[market_id] = defaults
        after = self.market(market_id).defaults
        if after != before:
            self.market_defaults_changed.emit(market_id, after)

    def set_library_folder(self, folder: Path | str | None) -> None:
        self.library_folder = Path(folder) if folder else None
        self.reload_library()

    def reload_library(self) -> int:
        """Read the module library folder again. Returns how many modules it holds."""
        n, self.library_problems = load_library_folder(self.registry, self.library_folder)
        self.library_changed.emit()
        return n

    def focus_strategy(self, id: str | None) -> None:
        if id != self.focused_strategy:
            self.focused_strategy = id
            self.strategy_focused.emit(id)

    # ---- strategies: ids, names, deleting ---------------------------------------------
    def new_strategy_id(self) -> str:
        """A key for a new strategy, never shown and never reused, so a new strategy can't pick
        up the runs of an old one that had the same number."""
        while True:
            sid = f"s-{uuid.uuid4().hex[:8]}"
            if sid not in self.strategies and not self.runs.records(sid):
                return sid

    def new_strategy_name(self) -> str:
        """"Strategy N" with the lowest N no open strategy is called (names free up when closed)."""
        taken = set()
        for sid in self.strategies.ids():
            m = _NUMBERED.fullmatch(self.strategies.get(sid).name.strip())
            if m:
                taken.add(int(m.group(1)))
        n = 1
        while n in taken:
            n += 1
        return f"Strategy {n}"

    def strategy_footprint(self, strategy_id: str) -> StrategyFootprint:
        run_ids = [r.id for r in self.runs.records(strategy_id)]
        tests = sum(len(self.backtests.results(r)) for r in run_ids)
        running = len(self.runs.active_for(strategy_id)) + len(self.backtests.active_for(run_ids))
        return StrategyFootprint(len(run_ids), tests, running)

    def delete_strategy(self, strategy_id: str) -> StrategyFootprint:
        """Delete a strategy for good: cancel what of it is still going, then remove its runs, their
        backtest results, and the strategy (which frees its data). The default strategy's
        yardstick runs are shared by every strategy and stay. Returns what was removed."""
        if is_default(strategy_id):
            raise ValueError("the default strategy can't be deleted")
        gone = self.strategy_footprint(strategy_id)
        self.runs.deleted.add(strategy_id)  # anything of it that finishes later is dropped
        run_ids = [r.id for r in self.runs.records(strategy_id)]
        for job in self.runs.active_for(strategy_id):
            self.runs.cancel(job)
        for job in self.backtests.active_for(run_ids):
            self.backtests.cancel(job)
        for rid in run_ids:
            self.backtests.forget(rid)
            self.runs.remove(rid)
        self.strategies.remove(strategy_id)
        if self.focused_strategy == strategy_id:
            self.focus_strategy(None)
        return gone

    def _strategy_changed(self, strategy_id: str, graph: StrategyGraph) -> None:
        """A strategy lists the datasets it uses in ``settings["datasets"]``; keep ``used_by`` in step."""
        settings = getattr(graph, "settings", None) or {}
        ids = settings.get("datasets")
        if ids is None and settings.get("dataset"):
            ids = [settings["dataset"]]
        if ids is not None:
            self.datasets.sync_strategy(strategy_id, ids)
