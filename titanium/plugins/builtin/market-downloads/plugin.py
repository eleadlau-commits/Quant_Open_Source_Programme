from titanium.sdk import Databento, Library, Polygon


def setup(plugin):
    for cls in (Polygon, Databento):
        plugin.add(Library.DATA_SOURCES, cls.name, cls(), doc=cls.doc)
