"""
values.py - Arturo value types.

Arturo is a dynamically typed language whose runtime values are the same
objects the parser produces: "code is data".  This module defines those
value types together with the helpers used to compare, copy, convert and
print them.

Design notes
------------
* Every value derives from :class:`Value` and carries a ``kind`` string that
  matches Arturo's own ``:kind`` names (``:integer``, ``:block``, ...).
* Blocks, dictionaries and objects are **mutable and passed by reference**,
  exactly like in Arturo: ``b: a`` aliases ``a``; ``new a`` makes a copy.
* Functions are values too (:class:`Function`), with either a Python
  implementation (builtins) or a body block (user functions).
"""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------
# Arturo reports types as `:type` values.  We keep the canonical names in a
# table so `type`, `is?` and error messages stay consistent.
TYPES = {
    "null", "logical", "integer", "floating", "complex", "rational", "string",
    "char", "block", "inline", "dictionary", "object", "range", "word",
    "literal", "label", "path", "pathliteral", "pathlabel", "symbol", "type",
    "function", "regex", "version", "color", "unit", "quantity", "date",
    "binary", "attribute", "attributelabel", "nothing", "store", "error",
    "bytecode", "socket",
}


class Value:
    """Base class for every Arturo value."""

    kind = "nothing"
    # Arbitrary annotation values (`.function` metadata) live here.
    ann: Optional[Dict[str, "Value"]] = None

    # -- introspection ----------------------------------------------------
    def set_kind(self, kind):
        return self

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.kind} {self.data!r}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Value):
            return NotImplemented
        return self.kind == other.kind and same_value(self, other)

    def __hash__(self) -> int:
        return hash((self.kind, _hashable(getattr(self, "data", None))))


def _hashable(v):
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted(((k, _hashable(x)) for k, x in v.items())))
    if isinstance(v, Value):
        return (v.kind, _hashable(getattr(v, "data", None)))
    return v


# ---------------------------------------------------------------------------
# Scalar values
# ---------------------------------------------------------------------------
class Null(Value):
    kind = "null"
    data = None

    def __repr__(self):
        return "<null>"

    __hash__ = Value.__hash__


class Logical(Value):
    kind = "logical"

    def __init__(self, data=False):
        # True / False / "maybe"
        self.data = data

    def __bool__(self):
        return self.data is True

    __hash__ = Value.__hash__


class Integer(Value):
    kind = "integer"

    def __init__(self, data=0):
        self.data = int(data)

    def __int__(self):
        return self.data

    __hash__ = Value.__hash__


class Floating(Value):
    kind = "floating"

    def __init__(self, data=0.0):
        self.data = float(data)

    def __float__(self):
        return self.data

    __hash__ = Value.__hash__


class Rational(Value):
    kind = "rational"

    def __init__(self, num=0, den=1):
        if isinstance(num, Fraction):
            self.data = num
        else:
            self.data = Fraction(int(num), int(den))

    __hash__ = Value.__hash__


class Complex(Value):
    kind = "complex"

    def __init__(self, real=0.0, imag=0.0):
        if isinstance(real, complex):
            self.data = real
        else:
            self.data = complex(real, imag)

    __hash__ = Value.__hash__


class String(Value):
    kind = "string"

    def __init__(self, data=""):
        self.data = str(data)

    def __hash__(self):
        return hash(("string", self.data))


class Char(Value):
    kind = "char"

    def __init__(self, data=" "):
        self.data = data

    __hash__ = Value.__hash__


class Version(Value):
    kind = "version"

    def __init__(self, data="0.0.0"):
        self.data = str(data)

    __hash__ = Value.__hash__


class Color(Value):
    kind = "color"

    def __init__(self, data="#000000"):
        self.data = normalize_color(str(data))

    __hash__ = Value.__hash__


class Unit(Value):
    kind = "unit"

    def __init__(self, data=""):
        self.data = str(data)

    __hash__ = Value.__hash__


class Quantity(Value):
    kind = "quantity"

    def __init__(self, value=None, unit=""):
        self.value = value if value is not None else Integer(0)
        self.unit = str(unit)
        self.data = (self.value, self.unit)

    __hash__ = Value.__hash__


class Regex(Value):
    kind = "regex"

    def __init__(self, data="", flags=""):
        self.data = str(data)
        self.flags = flags
        try:
            self.compiled = re.compile(self.data, _re_flags(flags))
        except re.error:
            self.compiled = None

    __hash__ = Value.__hash__


class Binary(Value):
    kind = "binary"

    def __init__(self, data=b""):
        self.data = bytes(data)

    def __hash__(self):
        return hash(("binary", self.data))


class Date(Value):
    kind = "date"

    def __init__(self, data=None):
        self.data = data  # datetime.datetime

    __hash__ = Value.__hash__


class Void(Value):
    """Internal marker: a builtin that leaves nothing on the stack.

    Arturo's VM is stack based: ``if false [1]`` pushes *nothing*, which is
    why ``print if false [1]`` reports "not enough parameters".  The Python
    port reproduces that with this sentinel.
    """

    kind = "void"
    data = None

    __hash__ = Value.__hash__


class Nothing(Value):
    """Placeholder for an as-yet-unassigned value (Arturo's ``nothing``)."""

    kind = "nothing"
    data = None

    __hash__ = Value.__hash__


# ---------------------------------------------------------------------------
# Structural values
# ---------------------------------------------------------------------------
def freeze(value: "Value") -> "Value":
    """Mark a value (and its nested containers) as a frozen literal."""
    stack = [value]
    while stack:
        item = stack.pop()
        if getattr(item, "frozen", None) is True:
            continue
        if item.kind in ("block", "inline", "dictionary", "object"):
            try:
                item.frozen = True
            except AttributeError:  # pragma: no cover - defensive
                continue
            if item.kind in ("dictionary", "object"):
                stack.extend(item.data.values())
            else:
                stack.extend(item.data)
    return value


class Block(Value):
    kind = "block"
    frozen = False

    def __init__(self, data=None):
        self.data: List[Value] = list(data) if data is not None else []
        self.frozen = False

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def __getitem__(self, i):
        return self.data[i]

    def __hash__(self):
        return hash(("block", tuple(_hashable(x) for x in self.data)))


class Inline(Block):
    kind = "inline"


class Dictionary(Value):
    kind = "dictionary"
    frozen = False

    def __init__(self, data=None):
        self.data: Dict[str, Value] = dict(data) if data is not None else OrderedDefault()
        self.frozen = False

    def __hash__(self):
        return hash(("dictionary", tuple((k, _hashable(v)) for k, v in self.data.items())))


class OrderedDefault(dict):
    """Plain dict keeps insertion order in modern Python - alias for clarity."""


class Object(Value):
    kind = "object"
    frozen = False

    def __init__(self, proto=None, data=None):
        self.proto = proto
        self.data: Dict[str, Value] = dict(data) if data else {}
        self.frozen = False

    __hash__ = Value.__hash__


class Range(Value):
    kind = "range"

    def __init__(self, start=0, stop=0, step=1):
        self.data = (start, stop, step)

    @property
    def start(self):
        return self.data[0]

    @property
    def stop(self):
        return self.data[1]

    @property
    def step(self):
        return self.data[2]

    __hash__ = Value.__hash__


# ---------------------------------------------------------------------------
# Parser-level values (words, literals, paths, attributes, symbols)
# ---------------------------------------------------------------------------
class Word(Value):
    kind = "word"

    def __init__(self, data=""):
        self.data = str(data)

    def __hash__(self):
        return hash(("word", self.data))


class Literal(Value):
    kind = "literal"

    def __init__(self, data=""):
        self.data = str(data)

    def __hash__(self):
        return hash(("literal", self.data))


class Label(Value):
    """``name:`` - an assignment target (VariableStore)."""

    kind = "label"

    def __init__(self, data=""):
        self.data = str(data)

    __hash__ = Value.__hash__


class Path(Value):
    """``a\\b\\0`` - resolved at evaluation time."""

    kind = "path"

    def __init__(self, data=None):
        self.data = list(data) if data else []

    def __hash__(self):
        return hash(("path", tuple(_hashable(x) for x in self.data)))


class PathLiteral(Value):
    kind = "pathliteral"

    def __init__(self, data=None):
        self.data = list(data) if data else []

    __hash__ = Value.__hash__


class PathLabel(Value):
    kind = "pathlabel"

    def __init__(self, data=None):
        self.data = list(data) if data else []

    __hash__ = Value.__hash__


class Symbol(Value):
    kind = "symbol"

    def __init__(self, data=""):
        self.data = str(data)

    def __hash__(self):
        return hash(("symbol", self.data))


class Type(Value):
    kind = "type"

    def __init__(self, data=""):
        self.data = str(data)

    def __hash__(self):
        return hash(("type", self.data))


class Attribute(Value):
    kind = "attribute"

    def __init__(self, data=""):
        self.data = str(data)

    __hash__ = Value.__hash__


class AttributeLabel(Value):
    kind = "attributelabel"

    def __init__(self, data="", value=None):
        self.data = str(data)
        self.value = value

    __hash__ = Value.__hash__


class Error(Value):
    kind = "error"

    def __init__(self, data=None):
        self.data: Dict[str, Value] = data or {}

    __hash__ = Value.__hash__


class Function(Value):
    """A user function (``function [x][...]``) or a builtin."""

    kind = "function"

    def __init__(self, name="<closure>", params=None, body=None, arity=0,
                 impl: Optional[Callable] = None, attrs=None, inline=False,
                 exports=None, imports=None, memoize=False, pure=False,
                 doc=None):
        self.name = name
        self.params = list(params or [])      # list[Word | Literal | Block | Type]
        self.body = body                      # Block / Inline for user functions
        if params:
            self.arity = len([p for p in self.params if getattr(p, "kind", "") != "type"])
        else:
            self.arity = arity
        self.impl = impl                      # callable for builtins
        self.attrs = set(attrs or ())         # accepted attribute names
        self.inline = inline
        self.exports = exports
        self.imports = imports or {}
        self.memoize = memoize
        self.pure = pure
        self.doc = doc or {}
        self.data = name

    @property
    def is_builtin(self) -> bool:
        return self.impl is not None

    def __hash__(self):
        return hash(("function", self.name, id(self)))

    def __eq__(self, other):
        return self is other


class BuiltinFunction(Function):
    pass


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
NULL = Null()
NOTHING = Nothing()
VOID = Void()


def new_true():
    return Logical(True)


TRUE = Logical(True)
FALSE = Logical(False)
MAYBE = Logical("maybe")


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------
def kind_of(v: Value) -> str:
    return v.kind


def is_stringy(v: Value) -> bool:
    return v.kind in ("string", "char")


def is_number(v: Value) -> bool:
    return v.kind in ("integer", "floating", "rational", "complex")


def is_collection(v: Value) -> bool:
    return v.kind in ("block", "inline", "dictionary", "object", "range", "string")


def new_value_like(v: Value):
    if v.kind in ("block", "inline"):
        return v.__class__([])
    return Block([])


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------
def value_key(v: Value):
    """A hashable, value-based key (used for function memoization)."""
    k = v.kind
    if k in ("integer", "floating", "rational", "logical", "string", "char",
             "word", "literal", "label", "symbol", "type", "version", "color",
             "null", "nothing"):
        return (k, v.data)
    if k in ("block", "inline"):
        return (k, tuple(value_key(x) for x in v.data))
    if k in ("dictionary", "object"):
        return (k, tuple(sorted((name, value_key(val)) for name, val in v.data.items())))
    if k == "range":
        return (k, v.start, v.stop, v.step)
    if k == "date":
        return (k, str(v.data))
    if k == "function":
        return ("function", id(v))
    return (k, id(v))


def same_value(a: Value, b: Value) -> bool:
    """Structural equality used by ``=`` / ``equal?``."""
    if a is b:
        return True

    ka, kb = a.kind, b.kind

    if ka in ("integer", "floating", "rational") or kb in ("integer", "floating", "rational"):
        if ka in ("integer", "floating", "rational") and kb in ("integer", "floating", "rational"):
            return _num(a) == _num(b)
        # quantity vs number
        return False

    if ka != kb:
        # blocks and inlines compare equal (Arturo is lenient here)
        if {ka, kb} <= {"block", "inline"}:
            return _seq_eq(a.data, b.data)
        # a one-character string and a char are interchangeable
        if {ka, kb} <= {"string", "char"} and len(a.data) == 1 and len(b.data) == 1:
            return a.data == b.data
        return False

    if ka == "string" or ka == "char" or ka == "word" or ka == "literal" \
            or ka == "symbol" or ka == "version" or ka == "type" or ka == "label" \
            or ka == "unit" or ka == "color":
        return a.data == b.data
    if ka == "null" or ka == "nothing":
        return True
    if ka == "logical":
        return a.data == b.data
    if ka in ("block", "inline"):
        return _seq_eq(a.data, b.data)
    if ka == "dictionary":
        if len(a.data) != len(b.data):
            return False
        for k in a.data:
            if k not in b.data:
                return False
            if not same_value(a.data[k], b.data[k]):
                return False
        return True
    if ka == "object":
        return same_value(Dictionary(a.data), Dictionary(b.data)) and a.proto == b.proto
    if ka == "range":
        return a.data == b.data
    if ka in ("path", "pathliteral", "pathlabel"):
        return _seq_eq(a.data, b.data) if len(a.data) != len(b.data) else all(
            same_value(x, y) for x, y in zip(a.data, b.data))
    if ka == "quantity":
        return same_value(a.value, b.value) and a.unit == b.unit
    if ka == "complex":
        return a.data == b.data
    if ka == "regex":
        return a.data == b.data and a.flags == b.flags
    if ka == "date":
        return a.data == b.data
    if ka == "binary":
        return a.data == b.data
    if ka == "error":
        return a.data == b.data
    if ka == "function":
        return a is b
    return a is b


def _seq_eq(x, y) -> bool:
    if len(x) != len(y):
        return False
    return all(same_value(i, j) for i, j in zip(x, y))


def _num(v: Value):
    if v.kind == "integer":
        return v.data
    if v.kind == "floating":
        return v.data
    return v.data  # Fraction


# ---------------------------------------------------------------------------
# Copying
# ---------------------------------------------------------------------------
def copy_value(v: Value, deep: bool = True) -> Value:
    """``new`` semantics: a structurally independent copy."""
    k = v.kind
    if k in ("block", "inline"):
        return v.__class__([copy_value(x) if deep else x for x in v.data])
    if k == "dictionary":
        d = Dictionary()
        for key, val in v.data.items():
            d.data[key] = copy_value(val) if deep else val
        return d
    if k == "object":
        o = Object(v.proto)
        for key, val in v.data.items():
            o.data[key] = copy_value(val) if deep else val
        return o
    if k == "quantity":
        return Quantity(copy_value(v.value), v.unit)
    if k == "range":
        return Range(*v.data)
    return v


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
_COLOR_NAMES = {
    "red": "#FF0000", "green": "#00FF00", "blue": "#0000FF", "black": "#000000",
    "white": "#FFFFFF", "yellow": "#FFFF00", "cyan": "#00FFFF",
    "magenta": "#FF00FF", "gray": "#808080", "grey": "#808080",
    "orange": "#FFA500", "purple": "#800080", "pink": "#FFC0CB",
    "brown": "#A52A2A", "gold": "#FFD700", "silver": "#C0C0C0",
    "navy": "#000080", "teal": "#008080", "olive": "#808000",
    "lime": "#00FF00", "maroon": "#800000", "aqua": "#00FFFF",
    "fuchsia": "#FF00FF", "violet": "#EE82EE", "indigo": "#4B0082",
    "coral": "#FF7F50", "salmon": "#FA8072", "khaki": "#F0E68C",
    "lavender": "#E6E6FA", "beige": "#F5F5DC", "crimson": "#DC143C",
    "crimson": "#DC143C", "darkred": "#8B0000", "darkgreen": "#006400",
    "darkblue": "#00008B", "lightgray": "#D3D3D3", "lightgrey": "#D3D3D3",
}


def normalize_color(name: str) -> str:
    n = name.strip()
    low = n.lower()
    if low in _COLOR_NAMES:
        return _COLOR_NAMES[low]
    if n.startswith("#"):
        hexpart = n[1:]
        if re.fullmatch(r"[0-9a-fA-F]{3}", hexpart):
            return "#" + "".join(c * 2 for c in hexpart).upper()
        if re.fullmatch(r"[0-9a-fA-F]{6}", hexpart):
            return "#" + hexpart.upper()
        return "#" + hexpart.upper()
    return "#" + n.upper()


def _re_flags(flags: str) -> int:
    f = 0
    for ch in flags:
        if ch == "i":
            f |= re.IGNORECASE
        elif ch == "m":
            f |= re.MULTILINE
        elif ch == "s":
            f |= re.DOTALL
        elif ch == "x":
            f |= re.VERBOSE
    return f


def format_float(f: float) -> str:
    if f != f:
        return "NaN"
    if f == float("inf"):
        return "∞"
    if f == float("-inf"):
        return "-∞"
    if f == int(f) and abs(f) < 1e16:
        return f"{f:.1f}"
    return repr(f)


def to_string(v: Value) -> str:
    """Literal string form (used by ``to :string`` and inside blocks)."""
    k = v.kind
    if k == "string":
        return v.data
    if k == "char":
        return v.data
    if k == "integer":
        return str(v.data)
    if k == "floating":
        return format_float(v.data)
    if k == "logical":
        if v.data == "maybe":
            return "maybe"
        return "true" if v.data else "false"
    if k == "null":
        return "null"
    if k == "nothing":
        return "nothing"
    if k in ("block", "inline"):
        return "[" + " ".join(block_item_str(x) for x in strip_newlines(v.data)) + "]"
    if k == "dictionary":
        return "[" + " ".join(f"{key}:{block_item_str(val)}" for key, val in v.data.items()) + "]"
    if k == "object":
        return "[" + " ".join(f"{key}:{block_item_str(val)}" for key, val in v.data.items()) + "]"
    if k == "range":
        if v.step == 1:
            return f"{v.start}..{v.stop}"
        return f"{v.start}..{v.stop}..{v.step}"
    if k == "type":
        return ":" + v.data
    if k in ("word", "literal", "symbol", "label", "unit"):
        return v.data
    if k == "version":
        return v.data
    if k == "color":
        return v.data
    if k == "rational":
        return f"{v.data.numerator}/{v.data.denominator}"
    if k == "complex":
        return _complex_str(v.data)
    if k == "regex":
        return f"/{v.data}/"
    if k == "binary":
        return "".join(f"{b:02X}" for b in v.data)
    if k == "date":
        return v.data.isoformat() if v.data else "null"
    if k == "quantity":
        return f"{to_string(v.value)}`{v.unit}"
    if k == "function":
        return v.name
    if k == "path":
        return "\\".join(to_string(p) for p in v.data)
    if k == "pathliteral":
        return "'" + "\\".join(to_string(p) for p in v.data)
    if k == "error":
        return (
            (v.data.get("message").data if isinstance(v.data.get("message"), String) else "")
        )
    if k == "attribute":
        return "." + v.data
    if k == "attributelabel":
        return "." + v.data + ":"
    return ""


def _complex_str(c: complex) -> str:
    real = format_float(c.real)
    imag = format_float(abs(c.imag))
    sign = "+" if c.imag >= 0 else "-"
    return f"{real} {sign} {imag}i"


def strip_newlines(items: List[Value]) -> List[Value]:
    return [i for i in items if not isinstance(i, Symbol) or i.data not in ("\n",)]


def block_item_str(v: Value) -> str:
    """How a value looks when printed as an element of a block."""
    k = v.kind
    if k in ("string", "char"):
        return v.data
    if k in ("block", "inline"):
        return "[" + " ".join(block_item_str(x) for x in strip_newlines(v.data)) + "]"
    if k == "function":
        return v.name
    return to_string(v)


def print_str(v: Value) -> str:
    """What ``print`` writes for a single (non-block) argument."""
    if v.kind in ("block", "inline"):
        if not v.data:
            return ""
        return "".join(block_item_str(x) + " " for x in strip_newlines(v.data))
    return to_string(v)


# ---------------------------------------------------------------------------
# Truthiness
# ---------------------------------------------------------------------------
def is_truthy(v: Value) -> bool:
    """Arturo's "not false and not null" test (used by ``if``/``while``).

    Anything that is not ``false``/``maybe``/``null`` counts as true - even
    ``0``, ``""`` or an empty block.
    """
    k = v.kind
    if k == "logical":
        return v.data is True
    if k in ("null", "nothing"):
        return False
    return True


def is_true(v: Value) -> bool:
    """Strict test: only a logical ``true`` passes (used by ``select``)."""
    k = v.kind
    if k == "logical":
        return v.data is True or v.data == "maybe"
    if k in ("null", "nothing"):
        return False
    if k == "integer":
        return v.data != 0
    if k == "floating":
        return v.data != 0.0
    if k == "string":
        return v.data != ""
    if k in ("block", "inline"):
        return len(v.data) > 0
    if k == "dictionary":
        return len(v.data) > 0
    return True
