#!/usr/bin/env python3
"""
run_examples.py - the Arturo examples benchmark for the Python port.

The corpus is the official ``examples/`` tree of the Arturo repository
(``rosetta/`` + ``projecteuler/`` + ``_drafts/``).  Every example that ships
a matching ``.res`` file is a test case: the interpreter's stdout must match
the recorded output.

Usage::

    python3 benchmarks/run_examples.py                # run everything
    python3 benchmarks/run_examples.py -k sort        # only names matching
    python3 benchmarks/run_examples.py --json out.json
    python3 benchmarks/run_examples.py --reference    # compare to real arturo
    python3 benchmarks/run_examples.py --jobs 8

Exit code is 0 when every selected example passes.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(HERE, "examples")
sys.path.insert(0, ROOT)


def normalize(text: str) -> list:
    return [line.rstrip() for line in text.replace("\r\n", "\n").rstrip("\n").split("\n")]


def discover(pattern: str = "") -> list:
    out = []
    for dirpath, _dirs, files in os.walk(EXAMPLES):
        for name in sorted(files):
            if not name.endswith(".art"):
                continue
            path = os.path.join(dirpath, name)
            res = path[:-4] + ".res"
            if not os.path.exists(res):
                continue
            rel = os.path.relpath(path, EXAMPLES)
            if pattern and not re.search(pattern, rel, re.I):
                continue
            out.append(path)
    return sorted(out)


def run_one(path: str, timeout: float = 20.0) -> dict:
    """Run a single example in this process."""
    from arturo import Interpreter, ArturoError

    rel = os.path.relpath(path, EXAMPLES)
    expected = open(path[:-4] + ".res", encoding="utf-8", errors="replace").read()
    buffer = io.StringIO()
    started = time.time()
    error = None
    interp = Interpreter(out=buffer)
    cwd = os.getcwd()
    try:
        os.chdir(os.path.dirname(path))
        interp.exec_file(os.path.basename(path))
    except SystemExit:
        pass
    except ArturoError as exc:
        error = f"{exc.kind}: {exc.message}"
    except RecursionError:
        error = "RecursionError"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        if os.environ.get("PYART_TRACE"):
            error += "\n" + traceback.format_exc()
    finally:
        os.chdir(cwd)

    actual = buffer.getvalue()
    ok = normalize(actual) == normalize(expected)
    return {
        "name": rel,
        "ok": ok,
        "error": error,
        "expected": expected,
        "actual": actual,
        "seconds": round(time.time() - started, 3),
    }


def run_isolated(path: str, timeout: float = 20.0) -> dict:
    """Run one example in a subprocess so hangs/crashes are contained."""
    from concurrent.futures import ThreadPoolExecutor

    cmd = [sys.executable, os.path.abspath(__file__), "--single", path]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=os.path.dirname(os.path.abspath(__file__)) + "/..")
    except subprocess.TimeoutExpired:
        return {"name": os.path.relpath(path, EXAMPLES), "ok": False,
                "error": f"timeout after {timeout}s", "expected": "", "actual": "",
                "seconds": timeout}
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        data["seconds"] = round(time.time() - started, 3)
        return data
    except (json.JSONDecodeError, IndexError):
        return {"name": os.path.relpath(path, EXAMPLES), "ok": False,
                "error": f"crashed: {proc.stderr.strip().splitlines()[-1][:200] if proc.stderr.strip() else proc.returncode}",
                "expected": "", "actual": "", "seconds": round(time.time() - started, 3)}


def run_reference(path: str, binary: str, timeout: float = 20.0):
    try:
        proc = subprocess.run([binary, "--no-color", path], capture_output=True,
                              timeout=timeout, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", "--filter", default="", help="regex on example path")
    ap.add_argument("--json", default="", help="write detailed results as JSON")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--reference", metavar="ARTURO_BIN", default="",
                    help="recompute which examples the real Arturo runtime passes")
    ap.add_argument("--reference-list", default=os.path.join(HERE, "reference_pass.json"),
                    help="JSON list of examples the reference runtime passes")
    ap.add_argument("--all", action="store_true",
                    help="count every example, not only reference-passing ones")
    ap.add_argument("--show-fail", type=int, default=15, help="how many failures to print")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--single", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.single:
        result = run_one(args.single, args.timeout)
        print(json.dumps(result))
        return 0

    paths = discover(args.filter)
    if not paths:
        print("no examples found")
        return 1

    # Optionally restrict to the set the real Arturo runtime handles
    reference_ok = None
    if args.reference_list and os.path.exists(args.reference_list) and not args.all:
        with open(args.reference_list, encoding="utf-8") as fh:
            reference_ok = {os.path.join(EXAMPLES, name) for name in json.load(fh)}
    elif args.reference:
        reference_ok = set()
        for path in paths:
            code, out, _err = run_reference(path, args.reference, args.timeout)
            if code == 0 and normalize(out) == normalize(open(path[:-4] + ".res", encoding="utf-8", errors="replace").read()):
                reference_ok.add(path)

    results = []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_isolated, p, args.timeout): p for p in paths}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                results.append({"name": os.path.relpath(futures[future], EXAMPLES),
                                "ok": False, "error": f"worker crashed: {exc}",
                                "expected": "", "actual": "", "seconds": 0})

    results.sort(key=lambda r: r["name"])
    if reference_ok is not None:
        in_scope = [r for r in results if os.path.join(EXAMPLES, r["name"]) in reference_ok]
        out_of_scope = [r for r in results if os.path.join(EXAMPLES, r["name"]) not in reference_ok]
    else:
        in_scope = results
        out_of_scope = []

    total = len(in_scope)
    passed = [r for r in in_scope if r["ok"]]
    failed = [r for r in in_scope if not r["ok"]]
    extra_passed = [r for r in out_of_scope if r["ok"]]

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)

    if not args.quiet:
        for r in failed[: args.show_fail]:
            print(f"✗ {r['name']}")
            if r["error"]:
                print(f"    error: {r['error'].splitlines()[0][:160]}")
            else:
                exp = normalize(r["expected"])
                act = normalize(r["actual"])
                for i in range(min(len(exp), len(act))):
                    if exp[i] != act[i]:
                        print(f"    first difference at line {i + 1}:")
                        print(f"      expected: {exp[i][:120]!r}")
                        print(f"      actual:   {act[i][:120]!r}")
                        break
                else:
                    print(f"    length differs: expected {len(exp)} lines, got {len(act)}")

    print()
    print(f"passed {len(passed)}/{total} examples ({100.0 * len(passed) / max(total,1):.1f}%)")
    if extra_passed:
        print(f"plus {len(extra_passed)} examples the reference runtime itself cannot run")
    return 0 if len(passed) == total else 1


if __name__ == "__main__":
    sys.exit(main())
