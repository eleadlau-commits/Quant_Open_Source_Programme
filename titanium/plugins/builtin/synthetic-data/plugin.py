from titanium.sdk import Library, SyntheticFutures, SyntheticStocks


def setup(plugin):
    for cls in (SyntheticStocks, SyntheticFutures):
        plugin.add(Library.DATA_SOURCES, cls.name, cls(), doc=cls.doc)
