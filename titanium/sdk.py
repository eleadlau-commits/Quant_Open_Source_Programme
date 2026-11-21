"""What strategy code and plugins import.

Strategy code: ``from titanium.sdk import knob, module``.

Plugins (see ``titanium/plugins``) may import only this module, numpy, pandas and a
short list of the standard library. Their ``plugin.py`` defines ``setup(plugin)``
and adds entries through the :class:`~titanium.app.plugins.PluginContext` it is given::

    from titanium.sdk import Library, Param, Source

    class MySource(Source):
        name = "my_source"
        ...

    def setup(plugin):
        plugin.add(Library.DATA_SOURCES, MySource.name, MySource(), doc=MySource.doc)

The ready-made pieces the app ships with (its sources, generators and starter
modules) are here too, so the built-in plugins follow the same rule as yours.
"""
from .core.bars import MarketData
from .core.data import DataKind, DatasetInfo, Frequency, Param, SourceSpec
from .core.generators import BUILTIN_GENERATORS, RealisedVolatility
from .core.module_library import STARTER, STARTERS, ModuleTemplate
from .core.plugins import API_VERSION, Library
from .core.sources import Databento, Polygon, Source, SyntheticFutures, SyntheticStocks
from .core.strategy_code import knob, module

__all__ = [
    "knob", "module",
    # plugins
    "API_VERSION", "Library", "Param", "Source", "SourceSpec", "DatasetInfo", "DataKind", "Frequency",
    "MarketData", "ModuleTemplate", "STARTER",
    # what ships with the app
    "SyntheticStocks", "SyntheticFutures", "Polygon", "Databento", "RealisedVolatility",
    "BUILTIN_GENERATORS", "STARTERS",
]
