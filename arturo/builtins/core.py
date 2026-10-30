"""
core.py - arithmetic, comparison, logic, control flow, I/O and types.

This is the heart of the standard library: everything the examples corpus
uses on almost every line.
"""
from __future__ import annotations

import math
import re as _re
from fractions import Fraction
from typing import Dict, List

from .. import values as V
from ..evaluator import ArturoError, BreakSignal, ContinueSignal, ReturnSignal
from . import *
from . import inplace
from . import (VOID, attr, attr_true, builtin, collection_size, compare,
               fail, impl, is_num, num_result, print_value, seq_of, to_float,
               to_int, to_number, write_out)


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------
_inplace = inplace


def _add_values(a: V.Value, b: V.Value) -> V.Value:
    if is_num(a) and is_num(b):
        return num_result(to_number(a) + to_number(b))
    if a.kind == "char" and b.kind == "char":
        return V.String(a.data + b.data)
    if a.kind in ("block", "inline") and b.kind in ("block", "inline"):
        return V.Block(a.data + b.data)
    if a.kind == "string" and b.kind in ("string", "char"):
        return V.String(a.data + (b.data if b.kind == "string" else b.data))
    if a.kind == "dictionary" and b.kind == "dictionary":
        d = V.Dictionary(dict(a.data))
        d.data.update(b.data)
        return d
    if a.kind == "quantity" and b.kind == "quantity" and a.unit == b.unit:
        return V.Quantity(_add_values(a.value, b.value), a.unit)
    if a.kind == "logical" and b.kind == "logical":
        return V.Logical(V.is_true(a) or V.is_true(b))
    fail(f"cannot add {a.kind} and {b.kind}", "Type Error")


@impl("add")
def _add(ev, args):
    a = args[0]
    b = args[1]
    if a.kind == "integer" and b.kind == "integer":
        return V.Integer(a.data + b.data)
    a, setter = _inplace(ev, a)
    result = _add_values(a, b)
    if setter:
        setter(result)
    return result


@builtin("inc", arity=1)
def _inc_value(ev, args):
    """``inc`` on a non-literal simply returns the incremented value."""
    value = args[0]
    current, setter = _inplace(ev, value)
    result = _add_values(current, V.Integer(1))
    if setter:
        setter(result)
    return result


@builtin("dec", arity=1)
def _dec_value(ev, args):
    value = args[0]
    current, setter = _inplace(ev, value)
    result = _sub_values(current, V.Integer(1))
    if setter:
        setter(result)
    return result


@impl("inc")
def _inc(ev, args):
    a, setter = _inplace(ev, args[0])
    result = _add_values(a, V.Integer(1))
    if setter:
        setter(result)
    return result if not setter else result


@impl("sub")
def _sub(ev, args):
    a = args[0]
    b = args[1]
    if a.kind == "integer" and b.kind == "integer":
        return V.Integer(a.data - b.data)
    a, setter = _inplace(ev, a)
    if is_num(a) and is_num(b):
        result = num_result(to_number(a) - to_number(b))
    elif a.kind == "quantity" and b.kind == "quantity":
        result = V.Quantity(num_result(to_number(a.value) - to_number(b.value)), a.unit)
    elif a.kind in ("block", "inline"):
        items = [x for x in a.data if not V.same_value(x, b)]
        result = V.Block(items)
    elif a.kind == "string":
        result = V.String(a.data.replace(V.to_string(b), "", 1))
    else:
        fail(f"cannot subtract {b.kind} from {a.kind}", "Type Error")
    if setter:
        setter(result)
    return result


@impl("dec")
def _dec(ev, args):
    a, setter = _inplace(ev, args[0])
    if is_num(a):
        result = num_result(to_number(a) - 1)
    else:
        fail(f"cannot decrement {a.kind}", "Type Error")
    if setter:
        setter(result)
    return result


@impl("mul")
def _mul(ev, args):
    a = args[0]
    b = args[1]
    if a.kind == "integer" and b.kind == "integer":
        return V.Integer(a.data * b.data)
    a, setter = _inplace(ev, a)
    if is_num(a) and is_num(b):
        result = num_result(to_number(a) * to_number(b))
    elif a.kind in ("string", "block", "inline", "char") and b.kind == "integer":
        if a.kind == "string":
            result = V.String(a.data * b.data)
        elif a.kind == "char":
            result = V.String(a.data * b.data)
        else:
            result = V.Block(a.data * b.data)
    elif a.kind == "quantity" and is_num(b):
        result = V.Quantity(num_result(to_number(a.value) * to_number(b)), a.unit)
    elif a.kind == "logical" and b.kind == "logical":
        result = V.Logical(V.is_true(a) and V.is_true(b))
    else:
        fail(f"cannot multiply {a.kind} by {b.kind}", "Type Error")
    if setter:
        setter(result)
    return result


def _int_div(x: int, y: int) -> int:
    if y == 0:
        raise ArturoError("Arithmetic Error", "Division by zero")
    q = abs(x) // abs(y)
    return q if (x >= 0) == (y >= 0) else -q


@impl("div")
def _div(ev, args):
    a, setter = _inplace(ev, args[0])
    b = args[1]
    if a.kind == "integer" and b.kind == "integer":
        result = V.Integer(_int_div(a.data, b.data))
    elif is_num(a) and is_num(b):
        x, y = to_number(a), to_number(b)
        if y == 0:
            raise ArturoError("Arithmetic Error", "Division by zero")
        if a.kind == "rational" and b.kind == "rational":
            result = V.Rational(x / y)
        elif isinstance(x, int) and isinstance(y, int):
            result = V.Integer(_int_div(x, y))
        else:
            result = V.Floating(float(x) / float(y))
    elif a.kind == "quantity" and is_num(b):
        result = V.Quantity(num_result(to_number(a.value) / to_number(b)), a.unit)
    else:
        fail(f"cannot divide {a.kind} by {b.kind}", "Type Error")
    if setter:
        setter(result)
    return result


@impl("fdiv")
def _fdiv(ev, args):
    a, setter = _inplace(ev, args[0])
    b = args[1]
    if is_num(a) and is_num(b):
        y = to_number(b)
        if y == 0:
            raise ArturoError("Arithmetic Error", "Division by zero")
        result = V.Floating(float(to_number(a)) / float(y))
    elif a.kind == "quantity" and is_num(b):
        result = V.Quantity(V.Floating(float(to_number(a.value)) / to_number(b)), a.unit)
    else:
        fail(f"cannot divide {a.kind} by {b.kind}", "Type Error")
    if setter:
        setter(result)
    return result


@impl("mod")
def _mod(ev, args):
    a = args[0]
    b = args[1]
    if a.kind == "integer" and b.kind == "integer":
        y = b.data
        if y == 0:
            raise ArturoError("Arithmetic Error", "Division by zero")
        x = a.data
        r = abs(x) % abs(y)
        return V.Integer(r if x >= 0 else -r)
    a, setter = _inplace(ev, a)
    x, y = to_number(a), to_number(b)
    if y == 0:
        raise ArturoError("Arithmetic Error", "Division by zero")
    if isinstance(x, int) and isinstance(y, int):
        r = abs(x) % abs(y)
        result = V.Integer(r if x >= 0 else -r)
    else:
        result = V.Floating(math.fmod(float(x), float(y)))
    if setter:
        setter(result)
    return result


@impl("divmod")
def _divmod(ev, args):
    a, b = args
    x, y = to_int(a), to_int(b)
    q = _int_div(x, y)
    r = x - q * y
    return V.Block([V.Integer(q), V.Integer(r)])


@impl("pow")
def _pow(ev, args):
    a, setter = _inplace(ev, args[0])
    b = args[1]
    if a.kind == "integer" and b.kind == "integer":
        if b.data >= 0:
            result = V.Integer(a.data ** b.data)
        else:
            result = V.Floating(float(a.data) ** b.data)
    else:
        x, y = to_float(a), to_float(b)
        try:
            result = num_result(x ** y)
            if isinstance(result, V.Integer):
                result = V.Floating(float(x) ** y)
        except (OverflowError, ValueError):
            result = V.Floating(float("nan"))
    if setter:
        setter(result)
    return result


@impl("neg")
def _neg(ev, args):
    a, setter = _inplace(ev, args[0])
    if a.kind == "quantity":
        result = V.Quantity(_neg(ev, [a.value]), a.unit)
    elif is_num(a):
        result = num_result(-to_number(a))
    elif a.kind == "logical":
        result = V.Logical(not V.is_true(a))
    elif a.kind in ("block", "inline", "string"):
        result = a
    else:
        fail(f"cannot negate {a.kind}", "Type Error")
    if setter:
        setter(result)
    return result


@impl("abs")
def _abs(ev, args):
    a = args[0]
    if is_num(a):
        return num_result(abs(to_number(a)))
    if a.kind == "quantity":
        return V.Quantity(num_result(abs(to_number(a.value))), a.unit)
    fail(f"cannot get absolute value of {a.kind}", "Type Error")


@impl("sign")
def _sign(ev, args):
    x = to_number(args[0])
    return num_result(1 if x > 0 else (-1 if x < 0 else 0))


@impl("max")
def _max(ev, args):
    a = args[0]
    if is_num(a) and len(args) > 1:
        return V.Integer(_int_div(to_int(a), to_int(args[1]))) if False else a
    return a


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
@impl("equal?")
def _equal(ev, args):
    a, b = args
    if a.kind == b.kind:
        if a.kind in ("integer", "string", "logical", "char"):
            return V.TRUE if a.data == b.data else V.FALSE
    return V.Logical(V.same_value(a, b))


@impl("notEqual?")
def _not_equal(ev, args):
    return V.Logical(not V.same_value(args[0], args[1]))


@impl("same?")
def _same(ev, args):
    a, b = args
    return V.Logical(a is b or V.same_value(a, b))


@impl("less?")
def _less(ev, args):
    return V.Logical(compare(args[0], args[1]) < 0)


@impl("lessOrEqual?")
def _less_eq(ev, args):
    return V.Logical(compare(args[0], args[1]) <= 0)


@impl("greater?")
def _greater(ev, args):
    return V.Logical(compare(args[0], args[1]) > 0)


@impl("greaterOrEqual?")
def _greater_eq(ev, args):
    return V.Logical(compare(args[0], args[1]) >= 0)


@impl("between?")
def _between(ev, args):
    x, a, b = args
    return V.Logical(compare(x, a) >= 0 and compare(x, b) <= 0)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------
def _bitwise_binary(ev, args, fn_int, fn_bool):
    a, b = args
    if a.kind == "integer" and b.kind == "integer":
        return V.Integer(fn_int(a.data, b.data))
    return V.Logical(fn_bool(V.is_true(a), V.is_true(b)))


@impl("and")
def _and(ev, args):
    return _bitwise_binary(ev, args, lambda x, y: x & y, lambda x, y: x and y)


@impl("or")
def _or(ev, args):
    return _bitwise_binary(ev, args, lambda x, y: x | y, lambda x, y: x or y)


@impl("not")
def _not(ev, args):
    value = args[0]
    if value.kind == "integer":
        return V.Integer(~value.data)
    return V.Logical(not V.is_true(value))


@impl("xor")
def _xor(ev, args):
    return _bitwise_binary(ev, args, lambda x, y: x ^ y, lambda x, y: x != y)


@impl("nand")
def _nand(ev, args):
    return _bitwise_binary(ev, args, lambda x, y: ~(x & y), lambda x, y: not (x and y))


@impl("nor")
def _nor(ev, args):
    return _bitwise_binary(ev, args, lambda x, y: ~(x | y), lambda x, y: not (x or y))


@impl("xnor")
def _xnor(ev, args):
    return _bitwise_binary(ev, args, lambda x, y: ~(x ^ y), lambda x, y: x == y)


@builtin("shl", arity=2)
def _shl(ev, args):
    return V.Integer(to_int(args[0]) << to_int(args[1]))


@builtin("shr", arity=2)
def _shr(ev, args):
    return V.Integer(to_int(args[0]) >> to_int(args[1]))


def _lazy_bool(ev, args):
    """Return the truth values of the (possibly block) arguments."""
    out = []
    for a in args:
        if isinstance(a, V.Block):
            out.append(ev.do_block(a))
        else:
            out.append(a)
    return out


def _truth3(v):
    """Three-valued truth: ``True`` / ``False`` / ``"maybe"``."""
    if v.kind == "logical" and v.data == "maybe":
        return "maybe"
    return V.is_true(v)


@impl("and?")
def _and_q(ev, args):
    values = [_truth3(v) for v in _lazy_bool(ev, args)]
    if any(v is False for v in values):
        return V.Logical(False)
    if any(v == "maybe" for v in values):
        return V.Logical("maybe")
    return V.Logical(True)


@impl("or?")
def _or_q(ev, args):
    values = [_truth3(v) for v in _lazy_bool(ev, args)]
    if any(v is True for v in values):
        return V.Logical(True)
    if any(v == "maybe" for v in values):
        return V.Logical("maybe")
    return V.Logical(False)


@impl("not?")
def _not_q(ev, args):
    value = args[0]
    if isinstance(value, V.Block):
        value = ev.do_block(value)
    truth = _truth3(value)
    if truth == "maybe":
        return V.Logical("maybe")
    return V.Logical(not truth)


@impl("coalesce")
def _coalesce(ev, args):
    a, b = args
    if a.kind in ("null", "void") or (a.kind == "logical" and a.data is False):
        return b
    return a


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _print_common(ev, value, newline=True):
    """`print` evaluates block arguments, printing one value per item."""
    lines = attr_true(ev, "lines")
    if isinstance(value, V.Block):
        values = _eval_collect(ev, value)
        for item in values:
            write_out(ev, V.to_string(item) + ("\n" if lines else " "))
        if not lines and newline:
            write_out(ev, "\n")
        return VOID
    write_out(ev, V.to_string(value) + ("\n" if newline else ""))
    return VOID


@impl("print")
def _print(ev, args):
    return _print_common(ev, args[0])


@impl("prints")
def _prints(ev, args):
    return _print_common(ev, args[0], newline=False)


@builtin("inspect", arity=1, attrs=["muted", "compact", "index"])
def _inspect(ev, args):
    write_out(ev, _inspect_str(args[0]) + "\n")
    return VOID


def _inspect_str(value: V.Value, level: int = 0) -> str:
    pad = "   " * level
    k = value.kind
    if k == "block":
        if not value.data:
            return "[]"
        inner = "\n".join(_inspect_str(v, level + 1) for v in value.data)
        return "[\n" + inner + "\n" + pad + "]"
    if k == "dictionary":
        if not value.data:
            return "#[]"
        inner = "\n".join(f"{'   ' * (level + 1)}{key}: {_inspect_str(val, level + 1)}"
                          for key, val in value.data.items())
        return "#[\n" + inner + "\n" + pad + "]"
    if k == "function":
        return f"<function {value.name}>"
    return f"{V.to_string(value)} :{_type_name(value)}"


@builtin("input", arity=1)
def _input(ev, args):
    prompt = V.to_string(args[0])
    write_out(ev, prompt)
    try:
        line = input()
    except EOFError:
        line = ""
    return V.String(line)


@builtin("newline", arity=0)
def _newline(ev, args):
    write_out(ev, "\n")
    return VOID


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
def _type_name(v: V.Value) -> str:
    return v.kind


@impl("type")
def _type(ev, args):
    return V.Type(_type_name(args[0]))


@impl("type?")
def _type_q(ev, args):
    expected = args[0]
    name = expected.data if isinstance(expected, V.Type) else V.to_string(expected)
    return V.Logical(_type_name(args[1]) == name)


@impl("is?")
def _is(ev, args):
    expected, value = args
    name = expected.data if isinstance(expected, V.Type) else V.to_string(expected)
    return V.Logical(_type_name(value) == name)


@impl("to")
def _to(ev, args):
    target, value = args
    if isinstance(target, V.Type):
        name = target.data
    elif isinstance(target, V.Block) and target.data and all(isinstance(t, V.Type) for t in target.data):
        return convert_elementwise(ev, target, value)
    else:
        name = V.to_string(target)
    return convert(ev, name, value)


def convert(ev, name: str, value: V.Value) -> V.Value:
    return _convert_one(ev, name, value)


def convert_elementwise(ev, types: V.Block, value: V.Value) -> V.Value:
    """`to [:char] "abc"` - convert every element to the given type."""
    names = [t.data if isinstance(t, V.Type) else V.to_string(t) for t in types.data]
    if value.kind in ("block", "inline"):
        out = []
        for i, item in enumerate(value.data):
            out.append(convert(ev, names[min(i, len(names) - 1)], item))
        return V.Block(out)
    if len(names) == 1:
        name = names[0]
        if value.kind in ("string", "range", "dictionary"):
            items = seq_of(value)
            return V.Block([convert(ev, name, x) for x in items])
        return convert(ev, name, value)
    return convert(ev, names[0], value)


def _convert_one(ev, name: str, value: V.Value) -> V.Value:
    if name == "string":
        fmt = attr(ev, "format", None)
        if fmt is not None and value.kind == "date":
            from .. import nimtime

            return V.String(nimtime.format(value.data, fmt.data))
        if fmt is not None and is_num(value):
            pattern = fmt.data
            if "%" not in pattern and _re.match(
                    r"^[-+ 0#]*\d*(\.\d+)?[dxXobfeEgGsc]$", pattern):
                pattern = "%" + pattern
            try:
                number = to_number(value)
                if pattern.endswith(("d", "i", "x", "X", "o", "b")):
                    return V.String(pattern % int(number))
                return V.String(pattern % number)
            except (ValueError, TypeError):
                pass
        if value.kind == "block":
            return V.String(" ".join(V.block_item_str(x) for x in value.data))
        return V.String(V.to_string(value))
    if name == "integer":
        if value.kind == "string":
            text = value.data.strip()
            base = attr(ev, "base", None)
            digits = attr(ev, "digits", None)
            try:
                if base is not None:
                    return V.Integer(int(text, to_int(base)))
                if text.lower().startswith("0x"):
                    return V.Integer(int(text, 16))
                return V.Integer(int(float(text)) if ("." in text or "e" in text.lower()) else int(text))
            except ValueError:
                fail(f"cannot convert to integer: {text!r}", "Conversion Error")
        if value.kind == "char":
            return V.Integer(ord(value.data))
        if value.kind == "logical":
            return V.Integer(1 if value.data is True else 0)
        return V.Integer(to_int(value))
    if name == "floating":
        if value.kind == "string":
            try:
                return V.Floating(float(value.data.strip()))
            except ValueError:
                fail(f"cannot convert to floating: {value.data!r}", "Conversion Error")
        return V.Floating(to_float(value))
    if name == "rational":
        if value.kind == "string":
            text = value.data.strip()
            if "/" in text:
                a, b = text.split("/", 1)
                return V.Rational(int(a), int(b))
            return V.Rational(Fraction(text))
        return V.Rational(Fraction(to_number(value)))
    if name == "logical":
        return V.Logical(V.is_true(value))
    if name == "char":
        if value.kind == "integer":
            return V.Char(chr(value.data))
        return V.Char(V.to_string(value)[:1])
    if name == "block":
        if value.kind == "string":
            from ..parser import Parser

            return V.Block(Parser(value.data).parse())
        return V.Block(seq_of(value) if value.kind not in ("null", "void") else [])
    if name == "inline":
        return V.Inline(seq_of(value))
    if name == "dictionary":
        if value.kind == "dictionary":
            return value
        if value.kind == "object":
            return V.Dictionary(dict(value.data))
        if value.kind in ("block", "inline"):
            items = value.data
            out = {}
            i = 0
            while i < len(items):
                key = items[i]
                if isinstance(key, V.Label):
                    name = key.data
                elif isinstance(key, (V.Literal, V.Word, V.String)):
                    name = key.data
                else:
                    name = V.to_string(key)
                out[name] = items[i + 1] if i + 1 < len(items) else V.NULL
                i += 2
            return V.Dictionary(out)
        return V.Dictionary({})
    if name == "range":
        if value.kind == "range":
            return value
        if value.kind == "integer":
            return V.Range(1, value.data, 1)
        items = seq_of(value)
        return V.Range(to_int(items[0]), to_int(items[-1]), 1)
    if name == "word":
        return V.Word(V.to_string(value))
    if name == "literal":
        return V.Literal(V.to_string(value))
    if name == "label":
        return V.Label(V.to_string(value))
    if name == "binary":
        if value.kind == "string":
            data = value.data
            if attr_true(ev, "hex"):
                try:
                    return V.Binary(bytes.fromhex(data))
                except ValueError:
                    fail("cannot convert to binary", "Conversion Error")
            encoding = attr(ev, "encoding", None)
            enc = encoding.data if isinstance(encoding, V.String) else "utf-8"
            return V.Binary(data.encode(enc))
        if value.kind == "integer":
            length = to_int(attr(ev, "length", V.Integer(1)))
            return V.Binary(value.data.to_bytes(length, "big", signed=False))
        if value.kind == "block":
            return V.Binary(bytes(to_int(x) for x in value.data))
        return V.Binary(bytes(value.data))
    if name == "date":
        import datetime

        from .. import nimtime

        fmt = attr(ev, "format", None)
        if value.kind == "date":
            return value
        if value.kind == "string":
            try:
                return V.Date(nimtime.parse(value.data, fmt.data if fmt else None))
            except (ValueError, TypeError):
                fail("cannot parse date", "Conversion Error")
        if value.kind == "integer":
            return V.Date(datetime.datetime.fromtimestamp(value.data))
        if fmt is not None:
            try:
                return V.Date(nimtime.parse(V.to_string(value), fmt.data))
            except ValueError:
                fail("cannot parse date", "Conversion Error")
        return V.Date(value.data)
    if name == "quantity":
        unit = attr(ev, "unit", None)
        if value.kind == "block" and len(value.data) >= 2:
            return V.Quantity(value.data[0], V.to_string(value.data[1]))
        if unit is not None:
            return V.Quantity(value, unit.data)
        return V.Quantity(value, "")
    if name == "regex":
        return V.Regex(V.to_string(value))
    if name == "version":
        return V.Version(V.to_string(value))
    if name == "color":
        return V.Color(V.to_string(value))
    if name == "function":
        return value
    if name == "string":
        return V.String(V.to_string(value))
    spec = ev.ctx.library.lookup_type(name)
    if spec is not None:
        return _build_object(ev, name, spec, value)
    fail(f"cannot convert to :{name}", "Conversion Error")


def _build_object(ev, name: str, spec: dict, value: V.Value) -> V.Value:
    """Create an instance of a user type from a block/dictionary of values."""
    fields = spec.get("fields") or []
    obj = V.Object(proto=V.Type(name))
    if isinstance(value, V.Dictionary):
        for key, item in value.data.items():
            obj.data[key] = item
    elif isinstance(value, (V.Block, V.Inline)):
        items = value.data
        # initializer method?
        init = (spec.get("methods") or {}).get("init")
        if isinstance(init, V.Function):
            ev.call(init, list(items))
            for key in fields:
                obj.data[key] = ev.ctx.get(key, V.NULL)
            return obj
        for i, field in enumerate(fields):
            obj.data[field] = items[i] if i < len(items) else V.NULL
    else:
        if fields:
            obj.data[fields[0]] = value
    return obj



# --- stack / reflection helpers -------------------------------------------
@builtin("dup", arity=1)
def _dup(ev, args):
    """Duplicate the given value (and make non-returning calls return)."""
    return args[0]


@builtin("call", arity=2, attrs=["external", "expect"])
def _call(ev, args):
    target, params = args
    if isinstance(target, V.Literal):
        fn = ev.ctx.get(target.data)
    elif isinstance(target, (V.Word, V.String)):
        fn = ev.ctx.get(to_string(target))
    else:
        fn = target
    if not isinstance(fn, V.Function):
        fail(f"function not found: {V.to_string(target)}", "Name Error")
    items = list(params.data) if isinstance(params, V.Block) else [params]
    return ev.call(fn, items, name=fn.name)


@builtin("compare", arity=2)
def _compare(ev, args):
    from . import compare

    return V.Integer(compare(args[0], args[1]))


@builtin("convert", arity=2)
def _convert(ev, args):
    target, value = args
    name = target.data if isinstance(target, V.Type) else V.to_string(target)
    return convert(ev, name, value)


@builtin("define", arity=2)
def _define(ev, args):
    """`define :person [name surname]` - register a user type (prototype)."""
    target, prototype = args
    name = target.data if isinstance(target, V.Type) else V.to_string(target)
    fields: List[str] = []
    methods: Dict[str, V.Value] = {}
    if isinstance(prototype, V.Block):
        for item in prototype.data:
            if isinstance(item, V.Label):
                fields.append(item.data)
            elif isinstance(item, (V.Word, V.Literal)):
                fields.append(item.data)
            elif isinstance(item, V.Block):
                for sub in item.data:
                    if isinstance(sub, V.Label):
                        fields.append(sub.data)
            elif isinstance(item, V.Dictionary):
                for key, value in item.data.items():
                    fields.append(key)
                    if isinstance(value, V.Function):
                        methods[key] = value
    elif isinstance(prototype, V.Dictionary):
        for key, value in prototype.data.items():
            if isinstance(value, V.Function):
                methods[key] = value
            else:
                fields.append(key)
    ev.ctx.library.register_type(name, {"fields": fields, "methods": methods,
                                        "prototype": prototype})
    return V.Type(name)


@impl("is")
def _is_derivative(ev, args):
    target, prototype = args
    name = target.data if isinstance(target, V.Type) else V.to_string(target)
    fields = prototype.data if isinstance(prototype, V.Block) else list(prototype.data.keys())
    ev.ctx.library.register_type(name, {"fields": [V.to_string(f) for f in fields],
                                        "prototype": prototype})
    return V.Type(name)


def _eval_conditions(ev, block) -> List[V.Value]:
    """Evaluate a block of conditions (block items are executed)."""
    out: List[V.Value] = []
    items = block.data if isinstance(block, V.Block) else [block]
    for item in items:
        if isinstance(item, V.Block):
            out.append(ev.do_block(item))
        else:
            out.append(item)
    return out


@builtin("any?", arity=1)
def _any_q(ev, args):
    block = args[0]
    if not isinstance(block, V.Block):
        return V.Logical(V.is_true(block))
    for item in block.data:
        value = ev.do_block(item) if isinstance(item, V.Block) else item
        if value.kind == "logical" and value.data is True:
            return V.Logical(True)
    return V.Logical(False)


@builtin("all?", arity=1)
def _all_q(ev, args):
    block = args[0]
    if not isinstance(block, V.Block):
        return V.Logical(V.is_true(block))
    for item in block.data:
        value = ev.do_block(item) if isinstance(item, V.Block) else item
        if not (value.kind == "logical" and value.data is True):
            return V.Logical(False)
    return V.Logical(True)


@builtin("xor?", arity=2)
def _xor_q(ev, args):
    left, right = _truth3(args[0]), _truth3(args[1])
    if left == "maybe" or right == "maybe":
        return V.Logical("maybe")
    return V.Logical(left != right)


@builtin("nand?", arity=2)
def _nand_q(ev, args):
    left, right = _truth3(args[0]), _truth3(args[1])
    if left is False or right is False:
        return V.Logical(True)
    if left == "maybe" or right == "maybe":
        return V.Logical("maybe")
    return V.Logical(False)


@builtin("none?", arity=1)
def _none_q(ev, args):
    result = _any_q(ev, args)
    return V.Logical(not V.is_true(result))


def _fill(dims: List[int], value: V.Value, level: int = 0) -> V.Block:
    if level >= len(dims):
        return V.copy_value(value)
    return V.Block([_fill(dims, value, level + 1) for _ in range(dims[level])])


@builtin("array", arity=1, attrs=["of"])
def _array(ev, args):
    value = args[0]
    of = attr(ev, "of", None)
    if of is not None:
        if of.kind in ("block", "inline"):
            dims = [to_int(x) for x in of.data]
        else:
            dims = [to_int(of)]
        return _fill(dims, value)
    if isinstance(value, V.Block):
        return V.Block(ev.collect_block(value))
    if value.kind == "range":
        from .iterators import range_values

        return V.Block([V.Integer(i) for i in range_values(value)])
    return V.Block([value])


@builtin("dictionary", arity=1)
def _dictionary(ev, args):
    value = args[0]
    if value.kind == "dictionary":
        return value
    if not isinstance(value, V.Block):
        fail("cannot convert to dictionary", "Type Error")
    if attr_true(ev, "raw"):
        raw = V.Dictionary({})
        items = value.data
        index = 0
        while index + 1 < len(items):
            key = items[index]
            name = key.data if isinstance(key, (V.Word, V.Literal, V.String,
                                                V.Label, V.Symbol)) else V.to_string(key)
            raw.data[name] = items[index + 1]
            index += 2
        return raw
    result = V.Dictionary({})
    items = value.data
    i = 0
    while i < len(items):
        item = items[i]
        if not isinstance(item, V.Label):
            i += 1
            continue
        key = item.data
        j = i + 1
        group: List[V.Value] = []
        while j < len(items) and not isinstance(items[j], V.Label):
            group.append(items[j])
            j += 1
        if not group:
            result.data[key] = V.NULL
        elif len(group) == 1 and isinstance(group[0], (V.Block, V.Inline)):
            # blocks are lazy values: they are *not* executed here
            result.data[key] = group[0]
        else:
            result.data[key] = ev.do_block(V.Block(group))
        i = j
    return result


def _single_expr(value, ev):
    return value


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------
def _make_predicate(name: str, kind):
    def pred(ev, args):
        value = args[0]
        if kind is None:
            return V.Logical(value.kind in name)
        return V.Logical(value.kind == kind)

    return pred


_PREDICATES = {
    "null?": ("null",), "logical?": ("logical",), "integer?": ("integer",),
    "floating?": ("floating",), "string?": ("string",), "char?": ("char",),
    "block?": ("block", "inline"), "dictionary?": ("dictionary",),
    "object?": ("object",), "function?": ("function",), "word?": ("word",),
    "literal?": ("literal",), "path?": ("path", "pathliteral"),
    "attribute?": ("attribute",), "binary?": ("binary",), "date?": ("date",),
    "range?": ("range",), "rational?": ("rational",), "complex?": ("complex",),
    "symbol?": ("symbol",), "regex?": ("regex",), "version?": ("version",),
    "color?": ("color",), "quantity?": ("quantity",), "unit?": ("unit",),
    "error?": ("error",), "inline?": ("inline",), "nothing?": ("nothing",),
    "label?": ("label",), "pathLabel?": ("pathlabel",),
    "symbolLiteral?": ("symbol",), "pathLiteral?": ("pathliteral",),
    "attributeLabel?": ("attributelabel",),
}

for _name, _kinds in _PREDICATES.items():
    if _name in ("nothing?",):
        continue

    def _pred(ev, args, _kinds=_kinds):
        return V.Logical(args[0].kind in _kinds)

    REGISTRY.setdefault(_name, _pred)


@impl("true?")
def _true_q(ev, args):
    v = args[0]
    return V.Logical(v.kind == "logical" and v.data is True)


@impl("false?")
def _false_q(ev, args):
    v = args[0]
    return V.Logical(v.kind == "logical" and v.data is False)


@impl("maybe?")
def _maybe_q(ev, args):
    v = args[0]
    return V.Logical(v.kind == "logical" and v.data == "maybe")


@impl("defined?")
def _defined(ev, args):
    a = args[0]
    if isinstance(a, V.Literal):
        return V.Logical(ev.ctx.has(a.data))
    if isinstance(a, V.Word):
        return V.Logical(ev.ctx.has(a.data))
    return V.Logical(True)


@impl("function?")
def _function_q(ev, args):
    return V.Logical(args[0].kind == "function")


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------
def _condition_value(ev, cond):
    if isinstance(cond, V.Block):
        try:
            return ev.do_block(cond)
        except (BreakSignal, ContinueSignal):
            raise
    return cond


@impl("if")
def _if(ev, args):
    cond, body = args[0], args[1]
    value = _condition_value(ev, cond)
    if V.is_truthy(value):
        return ev.do_block(body) if isinstance(body, V.Block) else body
    return VOID


# --- Arturo 0.9 style `if?` / `else` -------------------------------------
@builtin("if?", arity=2)
def _if_q(ev, args):
    """`if?` runs the action *and* pushes the condition result (0.9 syntax)."""
    cond, body = args[0], args[1]
    truth = V.is_truthy(_condition_value(ev, cond))
    if truth:
        ev.do_block(body) if isinstance(body, V.Block) else body
    return V.Logical(truth)


@builtin("unless?", arity=2)
def _unless_q(ev, args):
    cond, body = args[0], args[1]
    truth = not V.is_truthy(_condition_value(ev, cond))
    if truth:
        ev.do_block(body) if isinstance(body, V.Block) else body
    return V.Logical(truth)


@builtin("else", arity=1)
def _else(ev, args):
    """Runs the block when the previous statement's value is false/null."""
    previous = ev.ctx.prev_pushed
    if previous is None or not V.is_truthy(previous):
        return ev.do_block(args[0])
    return VOID


@builtin("switch?", arity=3)
def _switch_q(ev, args):
    cond, then_branch, else_branch = args[0], args[1], args[2]
    truth = V.is_truthy(_condition_value(ev, cond))
    branch = then_branch if truth else else_branch
    result = ev.do_block(branch) if isinstance(branch, V.Block) else branch
    return result if result is not V.VOID else V.Logical(truth)


@impl("unless")
def _unless(ev, args):
    cond, body = args[0], args[1]
    value = _condition_value(ev, cond)
    if not V.is_truthy(value):
        return ev.do_block(body) if isinstance(body, V.Block) else body
    return VOID


@impl("switch")
def _switch(ev, args):
    cond, then_branch, else_branch = args[0], args[1], args[2]
    value = _condition_value(ev, cond)
    branch = then_branch if V.is_truthy(value) else else_branch
    if isinstance(branch, V.Block):
        return ev.do_block(branch)
    return branch


@impl("while")
def _while(ev, args):
    cond, body = args[0], args[1]
    from ..evaluator import BreakSignal, ContinueSignal

    result: V.Value = V.NULL
    count = 0
    always = isinstance(cond, V.Block) is False and cond.kind == "null"
    while True:
        if not always:
            value = _condition_value(ev, cond)
            if not V.is_truthy(value):
                break
        count += 1
        if count > 5_000_000:
            fail("loop limit exceeded")
        try:
            result = ev.do_block_unscoped(body)
        except BreakSignal:
            break
        except ContinueSignal:
            continue
    return result


@impl("until")
def _until(ev, args):
    # Arturo's ``until`` takes the *action* first, then the condition
    body, cond = args[0], args[1]
    from ..evaluator import BreakSignal, ContinueSignal

    result: V.Value = V.NULL
    while True:
        try:
            result = ev.do_block_unscoped(body)
        except BreakSignal:
            break
        except ContinueSignal:
            pass
        if V.is_truthy(_condition_value(ev, cond)):
            break
    return result


@impl("do")
def _do(ev, args):
    value = args[0]
    if value.kind == "string":
        from ..parser import Parser

        value = V.Block(Parser(value.data).parse())
    return ev.do_block_unscoped(value)


@impl("loop")
def _loop(ev, args):
    from .iterators import iter_loop

    return iter_loop(ev, args)


@impl("return")
def _return(ev, args):
    raise ReturnSignal(args[0] if args else V.NULL)


@impl("break")
def _break(ev, args):
    raise BreakSignal()


@impl("continue")
def _continue(ev, args):
    raise ContinueSignal()


@impl("ensure")
def _ensure(ev, args):
    message = attr(ev, "message", None)
    value = ev.do_block(args[0]) if isinstance(args[0], V.Block) else args[0]
    if value is not V.VOID and not V.is_true(value):
        text = message.data if isinstance(message, V.String) else "Assertion failed"
        raise ArturoError("Assertion Failed", text)
    return VOID


def _looks_like_code(block: V.Block) -> bool:
    return False


@impl("try")
def _try(ev, args):
    try:
        value = ev.do_block(args[0])
        return value if value is not V.VOID else V.NULL
    except ArturoError as err:
        return err.to_value()
    except (BreakSignal, ContinueSignal, ReturnSignal):
        raise
    except ZeroDivisionError:
        return ArturoError("Arithmetic Error", "Division by zero").to_value()


@impl("try?")
def _try_q(ev, args):
    result = _try(ev, args)
    return V.Logical(not (result.kind == "error"))


@impl("throws?")
def _throws(ev, args):
    try:
        ev.do_block(args[0])
        return V.Logical(False)
    except ArturoError:
        return V.Logical(True)


@impl("panic")
def _panic(ev, args):
    message = args[0]
    raise ArturoError("Panic", V.to_string(message))


@impl("throw")
def _throw(ev, args):
    value = args[0]
    kind = attr(ev, "as", None)
    if isinstance(value, V.Error):
        raise ArturoError(V.to_string(value.data.get("kind", V.String("User Error"))),
                          V.to_string(value.data.get("message", V.String(""))) )
    raise ArturoError("User Error", V.to_string(value))


@impl("case")
def _case(ev, args):
    value, matches = args
    if isinstance(matches, V.Dictionary):
        key = V.to_string(value)
        if key in matches.data:
            result = matches.data[key]
            return ev.do_block(result) if isinstance(result, V.Block) else result
        if "any" in matches.data:
            result = matches.data["any"]
            return ev.do_block(result) if isinstance(result, V.Block) else result
        return VOID
    if not isinstance(matches, V.Block):
        fail("cannot use non-block as case matches", "Type Error")

    values = _eval_collect(ev, matches)
    i = 0
    while i < len(values) - 1:
        candidate = values[i]
        if _case_matches(candidate, value):
            result = values[i + 1]
            if isinstance(result, V.Block):
                return ev.do_block(result)
            return result
        i += 2
    return VOID


def _case_matches(candidate: V.Value, value: V.Value) -> bool:
    if candidate.kind == "word" and candidate.data == "any":
        return True
    if candidate.kind == "logical" and candidate.data is True:
        return V.is_true(value)
    return V.same_value(candidate, value)


def _eval_collect(ev, block: V.Block) -> List[V.Value]:
    """Evaluate a block and collect one value per statement (no newlines)."""
    tree = ev._tree_for(block)
    out: List[V.Value] = []
    for child in tree.children:
        value = ev.eval_node(child)
        if value is not V.VOID:
            out.append(value)
    return out


@builtin("when?", arity=1)
def _when_q(ev, args):
    block = args[0]
    if not isinstance(block, V.Block):
        return V.Logical(False)
    values = _eval_collect(ev, block)
    i = 0
    while i < len(values) - 1:
        if V.is_true(values[i]):
            result = values[i + 1]
            ev.do_block(result) if isinstance(result, V.Block) else None
            return V.Logical(True)
        i += 2
    return V.Logical(False)


@impl("when")
def _when(ev, args):
    block = args[0]
    if not isinstance(block, V.Block):
        return VOID
    values = _eval_collect(ev, block)
    i = 0
    while i < len(values) - 1:
        cond = values[i]
        if V.is_true(cond):
            result = values[i + 1]
            return ev.do_block(result) if isinstance(result, V.Block) else result
        i += 2
    return VOID


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------
def make_function(ev, params_block, body_block, name="<closure>"):
    params: List[V.Value] = []
    if isinstance(params_block, V.Literal):
        params = [V.Word(params_block.data)]
    elif isinstance(params_block, V.Block):
        for item in params_block.data:
            if isinstance(item, V.Type):
                continue
            if isinstance(item, V.Label):
                params.append(V.Word(item.data))
                continue
            params.append(item)
    elif isinstance(params_block, V.Word):
        params = [params_block]

    fn = V.Function(name=name, params=params, body=body_block,
                    arity=len([p for p in params if not isinstance(p, V.Type)]))
    fn.inline = attr_true(ev, "inline")
    exports = attr(ev, "export", None)
    if exports is not None:
        fn.exports = exports if isinstance(exports, V.Block) else V.Block([exports])
    imports = attr(ev, "import", None)
    if imports is not None:
        captured = {}
        items = imports.data if isinstance(imports, V.Block) else [imports]
        for item in items:
            key = item.data if isinstance(item, (V.Literal, V.Word)) else V.to_string(item)
            if key in ev.ctx.syms:
                captured[key] = ev.ctx.syms[key]
            else:
                lib_fn = ev.ctx.library.lookup(key)
                if lib_fn is not None:
                    captured[key] = lib_fn
        fn.imports = captured
    if attr_true(ev, "memoize"):
        fn.memoize = True
    if attr_true(ev, "pure"):
        fn.pure = True
    return fn


@impl("function")
def _function(ev, args):
    params, body = args
    return make_function(ev, params, body)


@builtin("method", arity=2)
def _method(ev, args):
    return make_function(ev, args[0], args[1])


@impl("var")
def _var(ev, args):
    a = args[0]
    if isinstance(a, V.Literal):
        return ev.ctx.get(a.data)
    if isinstance(a, V.PathLiteral):
        getter, _ = ev.inplace_target(a)
        return getter()
    if isinstance(a, (V.Word, V.String)):
        return ev.ctx.get(a.data)
    if isinstance(a, V.Block):
        return ev.do_block(a)
    fail("cannot use value as a literal", "Type Error")


def _destructure(ev, target: V.Block, value: V.Value) -> V.Value:
    """`[a b c]: [1 2 3]` - assign one value per name."""
    items = value.data if isinstance(value, V.Block) else [value]
    for name, item in zip(target.data, items):
        if isinstance(name, (V.Word, V.Literal)):
            ev.ctx.set(name.data, item)
        elif isinstance(name, V.Block):
            _destructure(ev, name, item)
    return value


@impl("let")
def _let(ev, args):
    target, value = args
    if isinstance(target, V.Block):
        return _destructure(ev, target, value)
    if isinstance(target, (V.Literal, V.PathLiteral)):
        _, setter = ev.inplace_target(target)
        setter(value)
        return value
    if isinstance(target, V.String):
        # ``let "name" value`` - define a variable by name
        ev.ctx.set(target.data, value)
        return value
    if isinstance(target, V.Word):
        ev.ctx.set(target.data, value)
        return value
    fail("cannot assign to non-literal", "Type Error")


@impl("alias")
def _alias(ev, args):
    name, target = args
    target_name = target.data if isinstance(target, (V.Literal, V.Word)) else V.to_string(target)
    fn = ev.ctx.library.lookup(target_name)
    if fn is None:
        candidate = ev.ctx.syms.get(target_name)
        if isinstance(candidate, V.Function):
            fn = candidate
    if fn is None:
        fail(f"function not found: {target_name}", "Name Error")
    names = []
    if isinstance(name, V.Block):
        names = [V.to_string(x) for x in name.data]
    else:
        names = [V.to_string(name)]
    for alias_name in names:
        if attr_true(ev, "infix"):
            from .. import ast as A

            A.DYNAMIC_INFIX[alias_name] = target_name
        elif attr_true(ev, "prefix"):
            ev.ctx.library.register(alias_name, fn.arity, fn.impl, attrs=fn.attrs)
        else:
            ev.ctx.library.register(alias_name, fn.arity, fn.impl, attrs=fn.attrs)
    return VOID


@impl("new")
def _new(ev, args):
    return V.copy_value(args[0])


@impl("attr")
def _attr_builtin(ev, args):
    name = args[0]
    key = name.data if isinstance(name, (V.Literal, V.Word)) else V.to_string(name)
    value = ev.ctx.pop_attr(key, V.NULL)
    return value


@impl("attrs")
def _attrs(ev, args):
    result = V.Dictionary({})
    for name, value in ev.ctx.attrs:
        result.data[name] = value
    ev.ctx.attrs = []
    return result


@impl("attr?")
def _attr_q(ev, args):
    name = args[0]
    key = name.data if isinstance(name, (V.Literal, V.Word)) else V.to_string(name)
    return V.Logical(ev.ctx.pop_attr(key, V.VOID) is not V.VOID)


@builtin("symbols", arity=0)
def _symbols(ev, args):
    result = V.Dictionary({})
    for name in ev.ctx.library.names():
        result.data[name] = V.NULL
    for name, value in ev.ctx.syms.items():
        result.data[name] = value
    return result


@impl("stack")
def _stack(ev, args):
    return V.Block([])


@builtin("env", arity=0)
def _env(ev, args):
    import os

    return V.Dictionary({k: V.String(v) for k, v in os.environ.items()})
