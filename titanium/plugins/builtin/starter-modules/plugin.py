import copy

from titanium.sdk import STARTER, STARTERS


def setup(plugin):
    for template in STARTERS:
        plugin.add_module(STARTER, copy.deepcopy(template))
