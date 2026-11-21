"""``python -m titanium.plugins new|check|pack|install|list|remove``.

    new <id> [--adds modules|data_sources|generators|backtests|skins] [--in FOLDER]
    check <folder or .tiplug> [--no-tests]
    pack <folder> [--out FOLDER]
    install <.tiplug or folder> [--replace] [--no-tests]
    list
    remove <id>
"""
from __future__ import annotations

import argparse
import sys

from ..app.plugins import PluginProblem
from . import pack as P


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m titanium.plugins", description="Make, check and install plugins.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("new", help="start a plugin folder from a template")
    a.add_argument("id")
    a.add_argument("--adds", default="modules", choices=list(P.TEMPLATES), help="what it adds")
    a.add_argument("--in", dest="base", default=None, help="where to make it (default: your plugins folder)")
    a.add_argument("--author", default="")
    a = sub.add_parser("check", help="check a plugin folder or .tiplug without installing it")
    a.add_argument("path")
    a.add_argument("--no-tests", action="store_true")
    a = sub.add_parser("pack", help="pack a plugin folder into a .tiplug file")
    a.add_argument("folder")
    a.add_argument("--out", default=None)
    a = sub.add_parser("install", help="check a .tiplug and add it to your plugins")
    a.add_argument("path")
    a.add_argument("--replace", action="store_true")
    a.add_argument("--no-tests", action="store_true")
    sub.add_parser("list", help="every plugin, on or off, and why")
    a = sub.add_parser("remove", help="delete one of your plugins")
    a.add_argument("id")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "new":
            print(f"made {P.new(args.id, args.adds, args.base, args.author)}")
        elif args.cmd == "check":
            rep = P.check(args.path, run_tests=not args.no_tests)
            print(rep.text())
            return 0 if rep.ok else 1
        elif args.cmd == "pack":
            print(f"packed {P.pack(args.folder, args.out)}")
        elif args.cmd == "install":
            rep = P.install(args.path, replace=args.replace, run_tests=not args.no_tests)
            print(rep.text())
            return 0 if rep.ok else 1
        elif args.cmd == "list":
            for st in P.statuses():
                state = "on " if st.on else "off"
                line = f"{state}  {st.id:<24} {st.version:<8} {st.source:<8} {st.name}"
                print(line + (f"\n       {st.reason}" if st.reason else ""))
        elif args.cmd == "remove":
            print(f"removed {P.remove(args.id)}")
    except PluginProblem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
