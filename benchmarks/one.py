#!/usr/bin/env python3
"""Run a single benchmark example and show the diff / traceback.

    python3 benchmarks/one.py rosetta/abc.words.art
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from run_examples import EXAMPLES, normalize, discover  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pattern = sys.argv[1]
    paths = [p for p in discover() if pattern.lower() in p.lower()]
    if not paths:
        print("no example matches", pattern)
        return 1
    path = paths[0]
    print("===", os.path.relpath(path, EXAMPLES))
    print(open(path, encoding="utf-8").read())
    from arturo import Interpreter, ArturoError
    import io

    buf = io.StringIO()
    interp = Interpreter(out=buf)
    cwd = os.getcwd()
    error = None
    try:
        os.chdir(os.path.dirname(path))
        interp.exec_file(os.path.basename(path))
    except Exception:
        error = traceback.format_exc()
    finally:
        os.chdir(cwd)
    actual = buf.getvalue()
    expected = open(path[:-4] + ".res", encoding="utf-8").read()
    print("--- output ---")
    print(actual)
    if error:
        print("--- traceback ---")
        print(error[-3000:])
    exp = normalize(expected)
    act = normalize(actual)
    if exp == act:
        print("--- MATCH ---")
        return 0
    print("--- diff (expected vs actual) ---")
    for i in range(max(len(exp), len(act))):
        e = exp[i] if i < len(exp) else "<missing>"
        a = act[i] if i < len(act) else "<missing>"
        if e != a:
            print(f"line {i+1}:\n  exp: {e[:200]!r}\n  got: {a[:200]!r}")
            if i > 30:
                break
    return 1


if __name__ == "__main__":
    sys.exit(main())
