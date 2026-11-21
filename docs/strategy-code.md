# Strategies as code

A strategy is a graph of modules (`titanium/core/strategy.py`). The graph is the source of
truth: it is what a strategy file (`.json`) holds, what the patch bay will draw, and what the
Code view shows as one Python file.

```python
"""Hold the strongest names that are above their moving average."""

from titanium.sdk import knob, module

SETTINGS = {"decide_at": "15:50", "every": "day"}

KNOBS = {"m3.top": 3}          # knobs turned away from their defaults (written by the Knobs dock)


@module(id="m1", name="Momentum", kind="transform", outputs=["scores"])
def momentum(view):
    days = knob("days", 20, lo=5, hi=120)
    ...
    return scores


@module(id="m3", name="Top N equal weight", kind="decide", links={"scores": "m1.scores"})
def top_n_equal_weight(scores):
    top = knob("top", 5, lo=1, hi=20)
    ...
    return {s: 1 / len(best) for s in best}
```

- **One function per module.** Its parameters are its input ports. `view` and `portfolio`
  (or `F` and `p`) are the decision-time context, not ports.
- **Links** sit on the module that receives them: `links={"input": "module_id.output"}`.
- **Knobs** are `knob("name", default, lo=, hi=)` calls. The type follows the default:
  `20` is a whole number, `0.5` is real, `True` is a switch. In the editor, put the cursor on a
  number and press **Ctrl+K** to make it a knob.
- **Shared code**: imports, helper functions and constants above the modules are kept as they
  are and every module can use them.
- **The decision**: the `decide` module returns target weights (`{instrument: fraction}`),
  a list of orders, or a `Decision`.
- Where a module sits on the canvas and which library entry it came from are kept in the graph,
  not in the code.

A plain Python file with no `@module` (a `decide(F, p)` file from the prototype) imports as a
one-module strategy: `decide` becomes the module, everything else becomes shared code. Add
`@module(...)` above other functions to split it into more modules.

Code: `titanium/core/strategy_code.py` (generate, parse, Make knob),
`titanium/core/strategy_compile.py` (graph to a runnable `Strategy`),
`titanium/core/module_library.py` (the module library and its starter folder).
