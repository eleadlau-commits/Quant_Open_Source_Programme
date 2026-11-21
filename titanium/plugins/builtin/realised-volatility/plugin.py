from titanium.sdk import Library, RealisedVolatility


def setup(plugin):
    plugin.add(Library.GENERATORS, RealisedVolatility.name, RealisedVolatility(), doc=RealisedVolatility.doc)
