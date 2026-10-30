"""
cli.py - command line entry point (``python3 -m arturo.cli script.art``).
"""
from __future__ import annotations

import sys

from . import ArturoError, Interpreter, values as V


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print("usage: arturo <script.art> [-- args...]\n"
              "       arturo -e '<code>'\n"
              "       arturo            (start the REPL)")
        return 0
    if not argv:
        from .repl import start_repl
        start_repl()
        return 0
    if argv[0] in ("-v", "--version"):
        print("arturo (python port) 0.1.0")
        return 0

    if argv[0] in ("-e", "--eval"):
        if len(argv) < 2:
            print("usage: arturo -e '<code>'", file=sys.stderr)
            return 1
        interp = Interpreter(argv=["<eval>"])
        try:
            interp.exec(argv[1])
        except ArturoError as exc:
            print(f"{exc.kind}: {exc.message}", file=sys.stderr)
            return 1
        return 0

    path = argv[0]
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    interp = Interpreter(argv=[path] + extra)
    try:
        interp.exec_file(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    except ArturoError as exc:
        print(f"{exc.kind}: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
