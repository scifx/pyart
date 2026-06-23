"""
values.py - Defines all Arturo value types.

Each value carries a ``kind`` (one of the :class:`K` enum members) and a
``data`` payload.  Equality and hashing are structural.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Tuple


class K(str, Enum):
    NULL = ":null"
    LOGICAL = ":logical"
    INTEGER = ":integer"
    FLOATING = ":floating"
    COMPLEX = ":complex"
    RATIONAL = ":rational"
    STRING = ":string"
    CHAR = ":char"
    BLOCK = ":block"
    DICTIONARY = ":dictionary"
    RANGE = ":range"
    WORD = ":word"
    LITERAL = ":literal"
    SYMBOL = ":symbol"
    TYPE = ":type"
    FUNCTION = ":function"
    PATH = ":path"
    REGEX = ":regex"
    VERSION = ":version"
    COLOR = ":color"
    UNIT = ":unit"
    QUANTITY = ":quantity"
    DATE = ":date"
    PATHLITERAL = ":pathliteral"
    SYMBOLLITERAL = ":symbolliteral"
    ATTRIBUTE = ":attribute"
    ATTRIBUTELABEL = ":attributelabel"
    LABEL = ":label"
    INLINE = ":inline"
    OBJECT = ":object"


class Value:
    """Base class for all Arturo values."""

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.kind} {self.data!r}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Value):
            return NotImplemented
        return self.kind == other.kind and _eq(self.data, other.data)

    def __hash__(self) -> int:
        return hash((self.kind, _hashable(self.data)))


# ---------------------------------------------------------------------------
# Helpers for structural equality / hashing
# ---------------------------------------------------------------------------
def _eq(a, b) -> bool:
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) == float(b)
        return False
    if isinstance(a, Value):
        return a == b
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a == b
    try:
        return a == b
    except Exception:
        return False


def _hashable(v):
    if isinstance(v, Value):
        return hash(v)
    if isinstance(v, (list, tuple)):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(val)) for k, val in v.items()))
    try:
        return hash(v)
    except TypeError:
        return hash(repr(v))


# ---------------------------------------------------------------------------
# Value classes
# ---------------------------------------------------------------------------
@dataclass
class VNull(Value):
    kind = K.NULL
    data: Any = None

    def __repr__(self) -> str:
        return "null"


@dataclass
class VLogical(Value):
    kind = K.LOGICAL
    data: Any = False  # True | False | "maybe"

    def __bool__(self) -> bool:
        return self.data is True


@dataclass
class VInteger(Value):
    kind = K.INTEGER
    data: Any = 0


@dataclass
class VFloating(Value):
    kind = K.FLOATING
    data: Any = 0.0


@dataclass
class VComplex(Value):
    kind = K.COMPLEX
    data: Any = (0.0, 0.0)


@dataclass
class VRational(Value):
    kind = K.RATIONAL
    data: Any = (1, 1)


@dataclass
class VString(Value):
    kind = K.STRING
    data: Any = ""

    def __repr__(self) -> str:
        return f'"{self.data}"'


@dataclass
class VChar(Value):
    kind = K.CHAR
    data: Any = ""


@dataclass
class VWord(Value):
    name: str = ""
    kind = K.WORD

    def __repr__(self) -> str:
        return self.name


@dataclass
class VLiteral(Value):
    name: str = ""
    kind = K.LITERAL

    def __repr__(self) -> str:
        return f"'{self.name}"


@dataclass
class VSymbol(Value):
    sym: str = ""
    kind = K.SYMBOL

    def __repr__(self) -> str:
        return self.sym


@dataclass
class VSymbolLiteral(Value):
    sym: str = ""
    kind = K.SYMBOLLITERAL

    def __repr__(self) -> str:
        return f"'{self.sym}"


@dataclass
class VType(Value):
    name: str = ""
    kind = K.TYPE

    def __repr__(self) -> str:
        return f":{self.name}"


@dataclass
class VLabel(Value):
    name: str = ""
    kind = K.LABEL

    def __repr__(self) -> str:
        return f"{self.name}:"


@dataclass
class VBlock(Value):
    """A literal (un-evaluated) block of items."""

    items: List[Any] = field(default_factory=list)
    kind = K.BLOCK

    def __repr__(self) -> str:
        return "[" + " ".join(repr(i) for i in self.items) + "]"


@dataclass
class VInline(Value):
    items: List[Any] = field(default_factory=list)
    kind = K.INLINE


@dataclass
class VDictionary(Value):
    items: "OrderedDict[str, Any]" = field(default_factory=OrderedDict)
    kind = K.DICTIONARY

    def __repr__(self) -> str:
        body = ", ".join(f"{k}: {v!r}" for k, v in self.items.items())
        return f"#[{body}]"


@dataclass
class VRange(Value):
    start: int = 0
    end: int = 0
    step: int = 1
    kind = K.RANGE

    def __iter__(self):
        return iter(range(self.start, self.end + (1 if self.step > 0 else -1), self.step))

    def __repr__(self) -> str:
        return f"{self.start}..{self.end}"


@dataclass
class VRegex(Value):
    pattern: str = ""
    flags: str = ""
    compiled: Any = None
    kind = K.REGEX


@dataclass
class VVersion(Value):
    major: int = 0
    minor: int = 0
    patch: int = 0
    pre: str = ""
    build: str = ""
    kind = K.VERSION

    def __repr__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            s += f"-{self.pre}"
        if self.build:
            s += f"+{self.build}"
        return s


@dataclass
class VColor(Value):
    r: int = 0
    g: int = 0
    b: int = 0
    kind = K.COLOR

    def __repr__(self) -> str:
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"


@dataclass
class VUnit(Value):
    name: str = ""
    kind = K.UNIT

    def __repr__(self) -> str:
        return f"`{self.name}"


@dataclass
class VQuantity(Value):
    number: Any = 0
    unit: Any = None
    kind = K.QUANTITY


@dataclass
class VDate(Value):
    iso: str = ""
    kind = K.DATE


@dataclass
class VAttribute(Value):
    name: str = ""
    value: Any = None
    kind = K.ATTRIBUTE


@dataclass
class VPath(Value):
    root: Any = None
    key: Any = None
    kind = K.PATH


@dataclass
class VPathLiteral(Value):
    root: str = ""
    key: str = ""
    kind = K.PATHLITERAL


@dataclass
class VObject(Value):
    """A user-defined object (instance of a custom type).

    ``fields`` is an :class:`OrderedDict` of field-name -> value.
    ``type_name`` is the name of the defining type.
    """

    fields: "OrderedDict[str, Any]" = field(default_factory=OrderedDict)
    type_name: str = ""
    kind = K.OBJECT

    def __repr__(self) -> str:
        body = ", ".join(f"{k}: {v!r}" for k, v in self.fields.items())
        return f"<:{self.type_name} {body}>"


@dataclass
class VFunction(Value):
    """A user-defined function."""

    params: List[str] = field(default_factory=list)
    body: Any = None
    scope: Any = None
    attributes: Any = None
    kind = K.FUNCTION

    def __repr__(self) -> str:
        return f"function[{','.join(self.params)}]"


@dataclass
class VBuiltinFunction(Value):
    """A built-in library function."""

    name: str = ""
    arity: int = -1
    impl: Any = None
    attrs: Any = None
    kind = K.FUNCTION


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------
def Null(): return VNull()


def Logical(b):
    if b == "maybe":
        return VLogical(data="maybe")
    return VLogical(data=bool(b))


def Integer(n): return VInteger(data=int(n))


def Floating(n): return VFloating(data=float(n))


def Complex(r, i=0.0): return VComplex(data=(float(r), float(i)))


def Rational(n, d):
    return VRational(data=(int(n), int(d)))


def String(s): return VString(data=str(s))


def Char(c):
    if len(c) != 1:
        raise ValueError(f"VChar must be single char, got {c!r}")
    return VChar(data=c)


def Word(name): return VWord(name=name)


def Literal(name): return VLiteral(name=name)


def Symbol(s): return VSymbol(sym=s)


def SymbolLiteral(s): return VSymbolLiteral(sym=s)


def TypeVal(name): return VType(name=name)


def Block(items=None):
    return VBlock(items=list(items or []))


def Inline(items=None):
    return VInline(items=list(items or []))


def Dictionary(items=None):
    return VDictionary(items=items or OrderedDict())


def Range(start, end, step=1):
    return VRange(start=start, end=end, step=step)


def Regex(pattern, flags=""): return VRegex(pattern=pattern, flags=flags)


def Version(major, minor, patch, pre="", build=""):
    return VVersion(major=major, minor=minor, patch=patch, pre=pre, build=build)


def Color(r, g, b):
    return VColor(r=int(r) & 0xFF, g=int(g) & 0xFF, b=int(b) & 0xFF)


def Unit(name): return VUnit(name=name)


def Quantity(n, unit): return VQuantity(number=n, unit=unit)


def Date(iso): return VDate(iso=iso)


def Attribute(name, value=None): return VAttribute(name=name, value=value)


def Path(root, key): return VPath(root=root, key=key)


def PathLiteral(root, key): return VPathLiteral(root=root, key=key)


def Object(type_name, fields=None):
    return VObject(type_name=type_name, fields=fields or OrderedDict())


def Function(params, body, scope=None, attributes=None):
    return VFunction(params=params, body=body, scope=scope or {},
                    attributes=attributes or {})


def Builtin(name, arity, impl, attrs=None):
    return VBuiltinFunction(name=name, arity=arity, impl=impl, attrs=attrs or {})


# ---------------------------------------------------------------------------
# Truthiness
# ---------------------------------------------------------------------------
def truthy(v) -> bool:
    if v.kind == K.LOGICAL:
        return v.data is True
    if v.kind == K.NULL:
        return False
    if v.kind == K.INTEGER:
        return v.data != 0
    if v.kind == K.FLOATING:
        return v.data != 0.0
    if v.kind == K.STRING:
        return len(v.data) > 0
    if v.kind == K.BLOCK:
        return len(v.items) > 0
    if v.kind == K.DICTIONARY:
        return len(v.items) > 0
    if v.kind == K.OBJECT:
        return True
    return True


def unwrap(v):
    """Return the underlying Python representation (for arithmetic)."""
    if v.kind == K.INTEGER:
        return v.data
    if v.kind == K.FLOATING:
        return v.data
    if v.kind == K.LOGICAL:
        return 1 if v.data is True else (0 if v.data is False else -1)
    if v.kind == K.STRING:
        return v.data
    if v.kind == K.CHAR:
        return v.data
    if v.kind == K.NULL:
        return 0
    if v.kind == K.COLOR:
        return v.r << 16 | v.g << 8 | v.b
    return v.data


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def display(v) -> str:
    """Return a user-friendly string representation."""
    if v is None:
        return "null"
    if v.kind == K.NULL:
        return "null"
    if v.kind == K.LOGICAL:
        if v.data == "maybe":
            return "maybe"
        return "true" if v.data else "false"
    if v.kind == K.INTEGER:
        return str(v.data)
    if v.kind == K.FLOATING:
        return repr(v.data)
    if v.kind == K.STRING:
        return v.data
    if v.kind == K.CHAR:
        return v.data
    if v.kind == K.WORD:
        return v.name
    if v.kind == K.LITERAL:
        return f"'{v.name}"
    if v.kind == K.SYMBOL:
        return v.sym
    if v.kind == K.TYPE:
        return f":{v.name}"
    if v.kind == K.BLOCK:
        # If items are AST nodes, evaluate first
        if v.items and not isinstance(v.items[0], Value):
            from .evaluator import Evaluator, Context
            from .library import Library
            stub = Context(Library())
            evaluated = [Evaluator(stub).eval_expr(x) for x in v.items]
            return "[" + " ".join(display(x) for x in evaluated) + "]"
        return "[" + " ".join(display(i) for i in v.items) + "]"
    if v.kind == K.INLINE:
        return "(" + " ".join(display(i) for i in v.items) + ")"
    if v.kind == K.DICTIONARY:
        return "#[" + " ".join(f"{k}: {display(val)}" for k, val in v.items.items()) + "]"
    if v.kind == K.COLOR:
        return f"#{v.r:02X}{v.g:02X}{v.b:02X}"
    if v.kind == K.VERSION:
        s = f"{v.major}.{v.minor}.{v.patch}"
        if v.pre: s += f"-{v.pre}"
        if v.build: s += f"+{v.build}"
        return s
    if v.kind == K.RANGE:
        return f"{v.start}..{v.end}"
    if v.kind == K.UNIT:
        return f"`{v.name}"
    if v.kind == K.QUANTITY:
        u = v.unit
        if isinstance(u, VUnit):
            return f"{v.number}`{u.name}"
        return f"{v.number}`{u}"
    if v.kind == K.FUNCTION:
        if isinstance(v, VBuiltinFunction):
            return f"<builtin {v.name}>"
        return f"function[{','.join(v.params)}]"
    if v.kind == K.PATH:
        return f"{display(v.root)}\\{display(v.key)}"
    if v.kind == K.PATHLITERAL:
        return f"'{display(v.root)}\\{display(v.key)}"
    if v.kind == K.REGEX:
        return f"{{/{v.pattern}/{v.flags}}}"
    if v.kind == K.DATE:
        return v.iso
    if v.kind == K.OBJECT:
        body = ", ".join(f"{k}: {display(val)}" for k, val in v.fields.items())
        return f"<:{v.type_name} {body}>"
    if v.kind == K.SYMBOLLITERAL:
        return f"'{v.sym}"
    return repr(v)
