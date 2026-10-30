#!/usr/bin/env python3
"""Inventory of the Arturo builtins known to the Python port.

The port registers *every* name the reference implementation knows about
(``arturo/signatures.py``), but only some of them have a Python
implementation; the rest fall back to a stub that raises
``Not Implemented``.  This script prints the split, grouped so that the
remaining work can be picked off in batches.

    $ python3 tools/inventory.py            # plain text report
    $ python3 tools/inventory.py --markdown # the tables used in docs/
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arturo.builtins as B  # noqa: E402
from arturo.builtins import (  # noqa: F401,E402  (imported for registration)
    core, collections, strings, iterators, numbers, misc, dates,
)
from arturo.library import Library  # noqa: E402

MODULES = ["core", "collections", "strings", "iterators", "numbers", "misc",
           "dates"]

#: quantity-type predicates: ``length?``, ``pressure?``, ...
UNITS = {
    "acceleration", "angle", "angularVelocity", "area", "areaDensity",
    "capacitance", "charge", "conductance", "currency", "current",
    "currentDensity", "dataTransferRate", "density", "elastance",
    "electricField", "electricityPrice", "energy", "force", "frequency",
    "heatFlux", "illuminance", "inductance", "information", "jerk",
    "kinematicViscosity", "length", "luminosity", "luminousFlux",
    "magneticFieldStrength", "magneticFlux", "magneticFluxDensity", "mass",
    "massFlowRate", "molarConcentration", "moleFlowRate", "momentofInertia",
    "momentum", "permeability", "permittivity", "potential", "power",
    "pressure", "radiation", "radiationExposure", "resistance", "resistivity",
    "salary", "solidAngle", "specificVolume", "speed", "substance",
    "surfaceTension", "temperature", "thermalConductivity",
    "thermalInsulance", "time", "viscosity", "volume", "volumetricFlow",
    "waveNumber",
}

#: short notes for the non-trivial missing builtins
HINTS: Dict[str, str] = {
    "info": "reflection: keyword metadata (usage/args/attrs/returns)",
    "methods": "reflection: object/type method tables",
    "arity": "reflection: function arity at runtime",
    "arg": "reflection: runtime argv as a block",
    "eval": "evaluate a string of Arturo code (``do`` already does this)",
    "parse": "parse to an AST / value",
    "hash": "hashing (md5/sha1/sha256/…) — ``digest`` exists",
    "benchmark": "time a block N times",
    "clamp": "trivial numeric clamp",
    "conj": "complex conjugate",
    "absolute": "absolute value for quantities",
    "lower?": "string case predicate",
    "upper?": "string case predicate",
    "nor?": "logical nor (alias ``⊽``)",
    "xnor?": "logical xnor (alias ``⊻``/``↔``)",
    "in": "range/collection membership helper",
    "units": "quantity unit introspection",
    "iterator": "lazy iterator objects",
    "sortable": "whether a value can be sorted",
    "conforms?": "type conformance check",
    "with": "block with an injected value (``=>`` machinery exists)",
    "set?": "is-attribute-set predicate",
    "store": "bytecode/global store",
    "peek": "bytecode peek",
    "goto": "bytecode jump",
    "discard": "drop the top of the stack",
    "execute": "run a shell command and capture output",
    "process": "spawn a process",
    "cd": "change directory",
    "permissions": "file permission bits",
    "rename": "filesystem rename",
    "symlink": "filesystem symlink",
    "terminal": "terminal size/control",
    "pause": "sleep for a duration",
    "wait": "wait for a task",
    "serve": "http server (net)",
    "request": "http client (net)",
    "download": "http download (net)",
    "socket?": "tcp/udp sockets",
    "channel": "task channels",
    "database?": "sqlite database",
    "query": "sql query",
    "webview": "webview ui",
    "dialog": "ui dialog",
    "popup": "ui popup",
    "alert": "ui alert",
    "yield": "fibers/tasks",
    "color": "colour constructors (``blend``/``lighten``/…)",
    "palette": "colour palettes",
    "translate": "colour/graphics transform",
}


def collect():
    lib = Library()
    B.install(lib)
    total: Set[str] = set(lib.names())
    impl = {n: f.__module__.rsplit(".", 1)[-1] for n, f in B.REGISTRY.items() if n in total}
    stubs = sorted(total - set(impl))
    return total, impl, stubs


def group_stubs(stubs: List[str]):
    units = [n for n in stubs if n.endswith("?") and n[:-1] in UNITS]
    i18n = [n for n in stubs if any(ord(c) > 127 for c in n)]
    rest = [n for n in stubs if n not in units and n not in i18n]
    return units, i18n, sorted(rest)


def as_text(total, impl, stubs) -> str:
    units, i18n, rest = group_stubs(stubs)
    lines = [
        f"registered names : {len(total)}",
        f"implemented      : {len(impl)}",
        f"stubs            : {len(stubs)}",
        "",
        "implemented per module:",
    ]
    for mod in MODULES:
        names = sorted(n for n, m in impl.items() if m == mod)
        lines.append(f"  {mod:<12} {len(names):>3}")
    lines += ["", f"missing unit predicates ({len(units)}):",
              "  " + " ".join(units),
              "", f"missing translated aliases ({len(i18n)}):",
              "  " + " ".join(i18n),
              "", f"missing everything else ({len(rest)}):",
              "  " + " ".join(rest), ""]
    return "\n".join(lines)


def as_markdown(total, impl, stubs) -> str:
    units, i18n, rest = group_stubs(stubs)
    out: List[str] = []
    out.append("# Builtin status")
    out.append("")
    out.append("_Generated by `python3 tools/inventory.py --markdown > "
               "docs/BUILTIN_STATUS.md` — re-run it after adding builtins._")
    out.append("")
    out.append(f"`arturo/signatures.py` declares **{len(total)}** names. "
               f"**{len(impl)}** have a Python implementation, "
               f"**{len(stubs)}** are still stubs that raise `Not Implemented`.")
    out.append("")
    out.append("| module | implemented builtins |")
    out.append("| --- | ---: |")
    for mod in MODULES:
        names = [n for n, m in impl.items() if m == mod]
        out.append(f"| `arturo/builtins/{mod}.py` | {len(names)} |")
    out.append(f"| *(declared in `signatures.py` only — stubs)* | {len(stubs)} |")
    out.append(f"| **total registered** | **{len(total)}** |")
    out.append("")
    out.append(f"## Implemented ({len(impl)})")
    out.append("")
    for mod in MODULES:
        names = sorted(n for n, m in impl.items() if m == mod)
        out.append(f"**{mod}** — " + ", ".join(f"`{n}`" for n in names))
        out.append("")
    out.append(f"## Not implemented yet ({len(stubs)})")
    out.append("")
    out.append(f"### Quantity-type predicates ({len(units)})")
    out.append("")
    out.append("Return `true`/`false` for a quantity's unit family "
               "(`5 kg` → `mass?`). They only need a unit→family table, so they "
               "are the cheapest batch to add:")
    out.append("")
    out.append(", ".join(f"`{n}`" for n in units))
    out.append("")
    out.append(f"### Translated aliases ({len(i18n)})")
    out.append("")
    out.append("Chinese aliases of builtins that already exist "
               "(`打印` = `print`, `循环` = `loop`, …). Pure aliasing, no new "
               "behaviour:")
    out.append("")
    out.append(", ".join(f"`{n}`" for n in i18n))
    out.append("")
    out.append(f"### Everything else ({len(rest)})")
    out.append("")
    out.append(", ".join(f"`{n}`" for n in rest))
    out.append("")
    notes = [n for n in rest if HINTS.get(n)]
    if notes:
        out.append("Notes for the ones that need more than a few lines:")
        out.append("")
        for name in notes:
            out.append(f"* `{name}` — {HINTS[name]}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    total, impl, stubs = collect()
    if "--markdown" in sys.argv:
        print(as_markdown(total, impl, stubs))
    else:
        print(as_text(total, impl, stubs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
