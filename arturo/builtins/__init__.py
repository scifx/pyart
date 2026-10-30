"""
builtins - the Arturo standard library, implemented in Python.

Every module in this package registers functions on a shared
:class:`~arturo.library.Library` through :func:`builtin`.

A builtin implementation has the signature ``impl(ev, args) -> Value`` where
``ev`` is the :class:`~arturo.evaluator.Evaluator` (giving access to the
context, attributes and block evaluation) and ``args`` the evaluated
arguments in declaration order.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from .. import values as V
from ..evaluator import ArturoError, BreakSignal, ContinueSignal, MISSING, ReturnSignal
from ..library import Library
from ..signatures import ARITY, ATTRS

VOID = V.VOID


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def fail(message: str, kind: str = "Value Error") -> None:
    raise ArturoError(kind, message)


def name_error(name: str) -> None:
    raise ArturoError("Name Error", f"Identifier not found: {name}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
REGISTRY: Dict[str, Callable] = {}
_DECLARED: Dict[str, set] = {}
DECLARED_ARITY: Dict[str, int] = {}


def impl(name: str):
    """Register a Python implementation for an existing Arturo builtin."""

    def deco(fn):
        REGISTRY[name] = fn
        return fn

    return deco


def builtin(name: str, arity: int = -1, attrs=None):
    """Declare a brand new builtin (name, arity, accepted attributes)."""

    def deco(fn):
        REGISTRY[name] = fn
        _DECLARED[name] = set(attrs or ())
        if arity >= 0:
            DECLARED_ARITY[name] = arity
        return fn

    return deco


def install(library: Library) -> None:
    """Register every implemented builtin on ``library``."""
    from . import (core, collections, strings, iterators, numbers, misc, dates)  # noqa: F401

    names = set(REGISTRY) | set(ARITY) | set(DECLARED_ARITY)
    for name in sorted(names):
        arity = DECLARED_ARITY.get(name, ARITY.get(name, _arity_default(name)))
        attrs = ATTRS.get(name, set()) | _DECLARED.get(name, set())
        fn = REGISTRY.get(name)
        if fn is None:
            fn = _make_stub(name)
        library.register(name, arity, fn, attrs=attrs)


def _arity_default(name: str) -> int:
    return 1


def _make_stub(name: str):
    def stub(ev, args):
        fail(f"'{name}' is not implemented yet in the Python port", "Not Implemented")

    return stub


def arity_of(name: str) -> int:
    return ARITY.get(name, -1)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def is_num(v: V.Value) -> bool:
    return v.kind in ("integer", "floating", "rational")


def to_number(v: V.Value, what: str = "value"):
    if v.kind == "integer":
        return v.data
    if v.kind == "floating":
        return v.data
    if v.kind == "rational":
        return v.data
    if v.kind == "char":
        return ord(v.data) if len(v.data) == 1 else 0
    fail(f"cannot use {v.kind} as a number")


def to_int(v: V.Value) -> int:
    if v.kind == "integer":
        return v.data
    if v.kind == "floating":
        return int(v.data)
    if v.kind == "rational":
        return int(v.data)
    if v.kind == "logical":
        return 1 if v.data is True else 0
    if v.kind == "char":
        return ord(v.data)
    if v.kind == "string":
        try:
            return int(v.data.strip())
        except ValueError:
            fail(f"cannot convert to integer: {v.data!r}")
    fail(f"cannot convert {v.kind} to integer")


def to_float(v: V.Value) -> float:
    if v.kind == "floating":
        return v.data
    if v.kind == "integer":
        return float(v.data)
    if v.kind == "rational":
        return float(v.data)
    if v.kind == "string":
        try:
            return float(v.data.strip())
        except ValueError:
            fail(f"cannot convert to floating: {v.data!r}")
    fail(f"cannot convert {v.kind} to floating")


def num_result(value, like: V.Value = None) -> V.Value:
    """Wrap a Python number back into the most appropriate Arturo value."""
    if isinstance(value, bool):
        return V.Logical(value)
    if isinstance(value, int):
        return V.Integer(value)
    if isinstance(value, float):
        return V.Floating(value)
    if isinstance(value, complex):
        return V.Complex(value)
    from fractions import Fraction

    if isinstance(value, Fraction):
        return V.Rational(value)
    return V.Integer(int(value))


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def is_collection(v: V.Value) -> bool:
    return v.kind in ("block", "inline", "dictionary", "object", "range", "string", "binary")


def seq_of(v: V.Value) -> List[V.Value]:
    """Return the elements of a collection as a list of values."""
    k = v.kind
    if k in ("block", "inline"):
        return list(v.data)
    if k == "dictionary":
        return list(v.data.values())
    if k == "object":
        return list(v.data.values())
    if k == "range":
        return [V.Integer(i) for i in range_values(v)]
    if k == "string":
        return [V.Char(c) for c in v.data]
    if k == "binary":
        return [V.Integer(b) for b in v.data]
    if k == "null":
        return []
    fail(f"cannot use {k} as a collection")


def range_values(v: V.Range) -> range:
    """Expand an Arturo range; ``10..1`` counts down automatically."""
    start, stop, step = v.data
    if step == 0:
        step = 1
    if step > 0 and start > stop:
        step = -step
    if step > 0:
        return range(int(start), int(stop) + 1, int(step))
    return range(int(start), int(stop) - 1, int(step))


def as_block(v: V.Value) -> V.Block:
    if isinstance(v, V.Block):
        return v
    if is_collection(v):
        return V.Block(seq_of(v))
    return V.Block([v])


def collection_size(v: V.Value) -> int:
    k = v.kind
    if k in ("block", "inline"):
        return len(v.data)
    if k in ("dictionary", "object"):
        return len(v.data)
    if k == "string":
        return len(v.data)
    if k == "binary":
        return len(v.data)
    if k == "range":
        return len(range_values(v))
    fail(f"cannot get size of {k}")


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------
_TYPE_ORDER = {
    "integer": 0, "floating": 0, "rational": 0, "complex": 0,
    "char": 1, "string": 1, "logical": 2, "null": 3, "block": 4,
    "inline": 4, "dictionary": 5, "object": 5, "function": 6, "type": 7,
}


def compare(a: V.Value, b: V.Value, sensitive: bool = False) -> int:
    """Arturo's total ordering, used by ``<``/``>``/``sort``."""
    if is_num(a) and is_num(b):
        x, y = to_number(a), to_number(b)
        return (x > y) - (x < y)
    if a.kind != b.kind:
        ra = _TYPE_ORDER.get(a.kind, 9)
        rb = _TYPE_ORDER.get(b.kind, 9)
        if ra != rb:
            return (ra > rb) - (ra < rb)
        ka, kb = a.kind, b.kind
        return (ka > kb) - (ka < kb)
    k = a.kind
    if k == "string":
        x, y = a.data, b.data
        if not sensitive:
            x, y = x.lower(), y.lower()
        return (x > y) - (x < y)
    if k == "char":
        return (a.data > b.data) - (a.data < b.data)
    if k == "logical":
        x = 1 if a.data is True else (0 if a.data is False else -1)
        y = 1 if b.data is True else (0 if b.data is False else -1)
        return (x > y) - (x < y)
    if k in ("block", "inline"):
        for x, y in zip(a.data, b.data):
            c = compare(x, y, sensitive)
            if c:
                return c
        return (len(a.data) > len(b.data)) - (len(a.data) < len(b.data))
    if k == "date":
        return (a.data > b.data) - (a.data < b.data)
    if k == "version":
        return (a.data > b.data) - (a.data < b.data)
    return 0


def equals(a: V.Value, b: V.Value) -> bool:
    return V.same_value(a, b)


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------
def inplace(ev, arg):
    """Resolve a literal/path-literal argument to ``(value, setter)``.

    Arturo values are references, but builtins only mutate *in place* when the
    argument is a literal (``'xs ++ 4``); a plain expression argument gets a
    copy (``y: sort xs`` leaves ``xs`` untouched).
    """
    if isinstance(arg, (V.Literal, V.PathLiteral)):
        getter, setter = ev.inplace_target(arg)
        value = getter()
        if getattr(value, "frozen", False):
            value = V.copy_value(value, deep=False)
        return value, setter
    # a plain expression argument is never mutated in place: mutating builtins
    # work on a copy of it (``sort xs`` leaves ``xs`` untouched)
    if isinstance(arg, (V.Block, V.Inline, V.Dictionary, V.Object)):
        return V.copy_value(arg, deep=False), None
    if getattr(arg, "frozen", False):
        return V.copy_value(arg, deep=False), None
    return arg, None


def attr(ev, name: str, default=MISSING):
    """Pop ``name`` from the attribute stack (None when absent)."""
    val = ev.ctx.pop_attr(name, MISSING)
    if val is MISSING:
        return default
    return val


def attr_true(ev, name: str) -> bool:
    val = ev.ctx.pop_attr(name, MISSING)
    if val is MISSING:
        return False
    return V.is_true(val)


def attr_present(ev, name: str):
    return ev.ctx.pop_attr(name, MISSING)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_out(ev, text: str) -> None:
    out = ev.ctx.out
    if out is None:
        print(text, end="")
    else:
        out.write(text)


def print_value(ev, value: V.Value, newline: bool = True, lines: bool = False) -> None:
    if lines and isinstance(value, V.Block):
        for item in value.data:
            write_out(ev, V.print_str(item) + "\n")
        return
    text = V.print_str(value)
    write_out(ev, text + ("\n" if newline else ""))
