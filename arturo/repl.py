"""
repl.py - a tiny interactive Arturo REPL.
"""
from __future__ import annotations

from . import Interpreter


_PROMPT = "arturo> "


def start_repl() -> None:
    interp = Interpreter()
    print("Arturo mini interpreter (Python port) - type 'exit' to quit.")
    while True:
        try:
            line = input(_PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        stripped = line.strip()
        if stripped in ("exit", "quit"):
            return
        if not stripped:
            continue
        try:
            interp.exec(line)
        except Exception as exc:  # pragma: no cover
            print(f"Error: {exc}")


if __name__ == "__main__":  # pragma: no cover
    start_repl()
