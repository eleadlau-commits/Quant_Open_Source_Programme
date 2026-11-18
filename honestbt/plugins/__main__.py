"""Plugin tools from the command line.

    python -m honestbt.plugins list
    python -m honestbt.plugins new my-test --kind evaluator      # start a folder in your plugin folder
    python -m honestbt.plugins check path/to/my-test             # or a .tiplug file
    python -m honestbt.plugins pack path/to/my-test [--out DIR]  # -> my-test-0.1.0.tiplug
    python -m honestbt.plugins install my-test-0.1.0.tiplug [--replace]
    python -m honestbt.plugins off|on <id>
    python -m honestbt.plugins remove <id>
"""
from __future__ import annotations

import argparse
import sys

from . import PluginProblem, set_enabled, statuses, user_dir
from . import pack as packing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m honestbt.plugins", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every plugin, on or off, and why")
    p = sub.add_parser("new", help="start a plugin folder from a template")
    p.add_argument("id")
    p.add_argument("--kind", default="evaluator", help="evaluator, feature, strategy, signal, mapping, suite, preset")
    p.add_argument("--dir", default=None, help=f"where to create it (default: {user_dir()})")
    p.add_argument("--author", default="")
    p = sub.add_parser("check", help="check a folder or .tiplug without installing it")
    p.add_argument("path")
    p.add_argument("--no-tests", action="store_true")
    p = sub.add_parser("pack", help="pack a folder into a .tiplug file")
    p.add_argument("folder")
    p.add_argument("--out", default=None)
    p = sub.add_parser("install", help="check a .tiplug and add it to your plugin folder")
    p.add_argument("file")
    p.add_argument("--replace", action="store_true")
    for name in ("on", "off", "remove"):
        sub.add_parser(name).add_argument("id")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "list":
            for s in statuses():
                provides = "; ".join(f"{k}: {', '.join(v)}" for k, v in s.provides.items())
                extra = ", ".join(x for x in (provides, s.suites and f"suites: {', '.join(s.suites)}",
                                              s.presets and f"presets: {', '.join(s.presets)}") if x)
                print(f"{'on ' if s.state == 'on' else 'OFF'}  {s.id:<26} {s.version:<8} {s.source:<8} "
                      f"{s.reason or extra}")
            print(f"\nYour plugin folder: {user_dir()}")
        elif a.cmd == "new":
            folder = packing.new(a.id, a.kind, a.dir, a.author)
            print(f"Made {folder}. Edit plugin.py, then: python -m honestbt.plugins check {folder}")
        elif a.cmd == "check":
            rep = packing.check(a.path, run_tests=not a.no_tests)
            print(rep.text())
            return 0 if rep.ok else 1
        elif a.cmd == "pack":
            rep = packing.check(a.folder)
            if not rep.ok:
                print(rep.text())
                return 1
            print(f"Packed {packing.pack(a.folder, a.out)}")
        elif a.cmd == "install":
            rep = packing.install(a.file, replace=a.replace)
            print(rep.text())
            return 0 if rep.ok else 1
        elif a.cmd in ("on", "off"):
            set_enabled(a.id, a.cmd == "on")
            print(f"{a.id} is {a.cmd}; it takes effect the next time the app starts.")
        elif a.cmd == "remove":
            print(f"Removed {packing.remove(a.id)}")
    except PluginProblem as exc:
        print(f"Problem: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
