"""
numbers.py - math, trigonometry, statistics and number predicates.
"""
from __future__ import annotations

import math
import random as _random
from typing import List

from .. import values as V
from ..evaluator import ArturoError, MISSING
from . import *
from . import (attr, attr_true, fail, impl, is_num, num_result, seq_of,
               to_float, to_int, to_number)


def _num(v: V.Value):
    return to_number(v)


def _wrap(x):
    if isinstance(x, float):
        return V.Floating(x)
    return V.Integer(int(x))


def _float_fn(name, fn):
    def impl_fn(ev, args):
        value = args[0]
        if value.kind == "quantity":
            return V.Quantity(_wrap(fn(_num(value.value))), value.unit)
        return _wrap(fn(_num(value)))

    impl(name)(impl_fn)


for _name, _fn in [
    ("acos", math.acos), ("acosh", math.acosh), ("asin", math.asin),
    ("asinh", math.asinh), ("atan", math.atan), ("atanh", math.atanh),
    ("cos", math.cos), ("cosh", math.cosh), ("sin", math.sin),
    ("sinh", math.sinh), ("tan", math.tan), ("tanh", math.tanh),
    ("exp", math.exp), ("ln", math.log), ("cbrt", lambda x: math.copysign(abs(x) ** (1 / 3), x)),
    ("gamma", math.gamma), ("sec", lambda x: 1 / math.cos(x)),
    ("csec", lambda x: 1 / math.sin(x)), ("cot", lambda x: 1 / math.tan(x)),
    ("sech", lambda x: 1 / math.cosh(x)), ("coth", lambda x: 1 / math.tanh(x)),
    ("asinh", math.asinh), ("log10", math.log10), ("exp10", lambda x: 10 ** x),
]:
    _float_fn(_name, _fn)


@impl("sqrt")
def _sqrt(ev, args):
    value = args[0]
    if value.kind == "quantity":
        return V.Quantity(_wrap(math.sqrt(_num(value.value))), value.unit)
    result = math.sqrt(_num(value))
    return V.Floating(result)


@impl("log")
def _log(ev, args):
    x, base = _num(args[0]), _num(args[1])
    return V.Floating(math.log(x, base))


@impl("atan2")
def _atan2(ev, args):
    return V.Floating(math.atan2(_num(args[0]), _num(args[1])))


@impl("hypot")
def _hypot(ev, args):
    return V.Floating(math.hypot(_num(args[0]), _num(args[1])))


@impl("floor")
def _floor(ev, args):
    value = args[0]
    return V.Integer(math.floor(_num(value)))


@impl("ceil")
def _ceil(ev, args):
    value = args[0]
    return V.Integer(math.ceil(_num(value)))


@impl("round")
def _round(ev, args):
    value = args[0]
    to = attr(ev, "to", None)
    x = _num(value)
    if to is not None:
        return V.Floating(float(round(x, to_int(to))))
    return V.Floating(float(round(x)))


@impl("powmod")
def _powmod(ev, args):
    a, b, m = to_int(args[0]), to_int(args[1]), to_int(args[2])
    return V.Integer(pow(a, b, m))


@impl("gcd")
def _gcd(ev, args):
    values = args[0].data if isinstance(args[0], V.Block) else [args[0]]
    result = 0
    for v in values:
        result = math.gcd(result, to_int(v))
    return V.Integer(result)


@impl("lcm")
def _lcm(ev, args):
    values = args[0].data if isinstance(args[0], V.Block) else [args[0]]
    result = 1
    for v in values:
        result = abs(result * to_int(v)) // math.gcd(result, to_int(v)) if result else 0
    return V.Integer(result)


@impl("factorial")
def _factorial(ev, args):
    n = to_int(args[0])
    return V.Integer(math.factorial(n))


@builtin("factors", arity=1, attrs=["prime"])
def _factors(ev, args):
    """``factors`` - all divisors; ``factors.prime`` - prime factorisation."""
    n = abs(to_int(args[0]))
    if attr_true(ev, "prime"):
        out = []
        d = 2
        while d * d <= n:
            while n % d == 0:
                out.append(V.Integer(d))
                n //= d
            d += 1 if d == 2 else 2
        if n > 1:
            out.append(V.Integer(n))
        return V.Block(out)
    out = []
    i = 1
    while i * i <= n:
        if n % i == 0:
            out.append(V.Integer(i))
            if i != n // i:
                out.append(V.Integer(n // i))
        i += 1
    return V.Block(sorted(out, key=lambda v: v.data))



@impl("divisors")
def _divisors(ev, args):
    n = abs(to_int(args[0]))
    result = []
    i = 1
    while i * i <= n:
        if n % i == 0:
            result.append(V.Integer(i))
            if i != n // i:
                result.append(V.Integer(n // i))
        i += 1
    return V.Block(sorted(result, key=lambda v: v.data))


_MR_BASES_SMALL = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def _is_prime(n: int) -> bool:
    """Trial division for small numbers, Miller-Rabin beyond that.

    The reference implementation switches to GMP's ``probablyPrime`` for
    big integers, so a probabilistic test is exactly what Arturo does.
    """
    if n < 2:
        return False
    for p in _MR_BASES_SMALL:
        if n % p == 0:
            return n == p
    if n < 1000000 * 1000000:
        i = 41
        while i * i <= n:
            if n % i == 0 or n % (i + 2) == 0:
                return False
            i += 6
        return True
    # write n-1 as d * 2**s
    d = n - 1
    s = 0
    while d % 2 == 0:
        d //= 2
        s += 1
    bases = list(_MR_BASES_SMALL)
    if n >= 3317044064679887385961981:  # deterministic bases are not enough
        import random
        rnd = random.Random(0xA47)
        bases += [rnd.randrange(41, n - 2) for _ in range(20)]
    for a in bases:
        a %= n
        if a < 2:
            continue
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


@impl("prime?")
def _prime_q(ev, args):
    return V.Logical(_is_prime(to_int(args[0])))


@impl("clamp")
def _clamp(ev, args):
    value, bounds = args[0], args[1]
    if bounds.kind == "range":
        start, stop, step = bounds.data
        lo, hi = (start, stop) if (step or 1) >= 0 else (stop, start)
    elif bounds.kind in ("block", "inline") and len(bounds.data) >= 2:
        lo, hi = bounds.data[0], bounds.data[1]
    else:
        fail(f"cannot clamp using {bounds.kind}", "Type Error")
    def _wrap(x):
        if isinstance(x, V.Value):
            return x
        return V.Integer(x) if isinstance(x, int) else V.Floating(float(x))

    lo, hi = _wrap(lo), _wrap(hi)
    lo_v, hi_v = to_number(lo), to_number(hi)
    val = to_number(value)
    if val < lo_v:
        return lo
    if val > hi_v:
        return hi
    return value


@impl("conj")
def _conj(ev, args):
    value = args[0]
    if value.kind != "complex":
        fail(f"cannot get conjugate of {value.kind}", "Type Error")
    return V.Complex(complex(value.data.real, -value.data.imag))


@impl("digits")
def _digits(ev, args):
    value = args[0]
    base = attr(ev, "base", None)
    if base is not None and value.kind == "integer":
        b = to_int(base)
        n = abs(value.data)
        out = []
        while True:
            out.append(V.Integer(n % b))
            n //= b
            if n == 0:
                break
        return V.Block(list(reversed(out)))
    if value.kind == "integer":
        return V.Block([V.Integer(int(c)) for c in str(abs(value.data))])
    if value.kind == "string":
        return V.Block([V.Integer(int(c)) for c in value.data if c.isdigit()])
    return V.Block([V.Integer(int(c)) for c in str(value.data) if c.isdigit()])


@impl("numerator")
def _numerator(ev, args):
    value = args[0]
    if value.kind == "rational":
        return V.Integer(value.data.numerator)
    return V.Integer(to_int(value))


@impl("denominator")
def _denominator(ev, args):
    value = args[0]
    if value.kind == "rational":
        return V.Integer(value.data.denominator)
    return V.Integer(1)


@impl("reciprocal")
def _reciprocal(ev, args):
    value = args[0]
    if value.kind == "integer":
        return V.Rational(1, value.data)
    return V.Floating(1.0 / to_float(value))


@impl("random")
def _random_fn(ev, args):
    a, b = args[0], args[1]
    if a.kind in ("block", "inline"):
        return _random.choice(a.data)
    if a.kind == "string":
        return V.Char(_random.choice(a.data))
    lo, hi = to_int(a), to_int(b)
    if lo > hi:
        lo, hi = hi, lo
    return V.Integer(_random.randint(lo, hi))


# -- predicates --------------------------------------------------------------
def _pred(name, fn):
    def pred(ev, args):
        value = args[0]
        if value.kind in ("quantity",):
            value = value.value
        if not is_num(value):
            return V.Logical(False)
        return V.Logical(fn(to_number(value)))

    impl(name)(pred)


_pred("even?", lambda x: x % 2 == 0)
_pred("odd?", lambda x: x % 2 != 0)
_pred("zero?", lambda x: x == 0)
_pred("one?", lambda x: x == 1)


@impl("one?")
def _one_q(ev, args):
    value = args[0]
    if value.kind in ("block", "inline"):
        return V.Logical(len(value.data) == 1)
    if value.kind in ("dictionary", "object"):
        return V.Logical(len(value.data) == 1)
    if is_num(value):
        return V.Logical(to_number(value) == 1)
    if value.kind == "null":
        return V.Logical(False)
    return V.Logical(True)
_pred("positive?", lambda x: x > 0)
_pred("negative?", lambda x: x < 0)


@impl("even?")
def _even(ev, args):
    value = args[0]
    return V.Logical(is_num(value) and to_number(value) % 2 == 0)


@impl("odd?")
def _odd(ev, args):
    value = args[0]
    return V.Logical(is_num(value) and to_number(value) % 2 != 0)


@impl("zero?")
def _zero(ev, args):
    value = args[0]
    return V.Logical(is_num(value) and to_number(value) == 0)


@impl("numeric?")
def _numeric(ev, args):
    value = args[0]
    if is_num(value):
        return V.Logical(True)
    if value.kind == "string":
        text = value.data.strip()
        try:
            float(text)
            return V.Logical(True)
        except ValueError:
            return V.Logical(False)
    return V.Logical(False)


@impl("infinite?")
def _infinite(ev, args):
    value = args[0]
    if is_num(value):
        x = to_number(value)
        return V.Logical(x == float("inf") or x == float("-inf"))
    return V.Logical(False)


@impl("scalar")
def _scalar(ev, args):
    return V.Logical(args[0].kind in ("integer", "floating", "rational", "complex"))


# -- statistics --------------------------------------------------------------
def _stats_values(value: V.Value) -> List[float]:
    items = value.data if isinstance(value, V.Block) else list(seq_of(value))
    return [to_float(v) for v in items]


@impl("median")
def _median(ev, args):
    values = sorted(_stats_values(args[0]))
    if not values:
        return V.NULL
    n = len(values)
    if n % 2:
        value = values[n // 2]
        return V.Integer(int(value)) if value == int(value) else V.Floating(value)
    value = (values[n // 2 - 1] + values[n // 2]) / 2
    return V.Integer(int(value)) if value == int(value) else V.Floating(value)


@impl("variance")
def _variance(ev, args):
    values = _stats_values(args[0])
    if not values:
        return V.Floating(0.0)
    mean = sum(values) / len(values)
    return V.Floating(sum((x - mean) ** 2 for x in values) / len(values))


@impl("deviation")
def _deviation(ev, args):
    values = _stats_values(args[0])
    if not values:
        return V.Floating(0.0)
    mean = sum(values) / len(values)
    return V.Floating(math.sqrt(sum((x - mean) ** 2 for x in values) / len(values)))


@impl("skewness")
def _skewness(ev, args):
    values = _stats_values(args[0])
    n = len(values)
    if n < 2:
        return V.Floating(0.0)
    mean = sum(values) / n
    m2 = sum((x - mean) ** 2 for x in values) / n
    m3 = sum((x - mean) ** 3 for x in values) / n
    if m2 == 0:
        return V.Floating(0.0)
    return V.Floating(m3 / (m2 ** 1.5))


@impl("kurtosis")
def _kurtosis(ev, args):
    values = _stats_values(args[0])
    n = len(values)
    if n < 2:
        return V.Floating(0.0)
    mean = sum(values) / n
    m2 = sum((x - mean) ** 2 for x in values) / n
    m4 = sum((x - mean) ** 4 for x in values) / n
    if m2 == 0:
        return V.Floating(0.0)
    return V.Floating(m4 / (m2 ** 2) - 3)


# -- constants ---------------------------------------------------------------
def register_constants(library) -> None:
    library.constants = {
        # Arturo's numeric constants (``epsilon`` is Euler's number!)
        "pi": V.Floating(math.pi),
        "tau": V.Floating(math.tau),
        "epsilon": V.Floating(math.e),
        "infinite": V.Floating(float("inf")),
        "∞": V.Floating(float("inf")),
        # logic constants
        "true": V.TRUE,
        "false": V.FALSE,
        "maybe": V.Logical("maybe"),
        # nil-ish constants
        "null": V.NULL,
        "ø": V.NULL,
        "any": V.NOTHING,
        "_": V.NOTHING,
        # error kinds (used with ``try`` / ``panic``)
        **{
            name: V.String(name[:1].upper() + name[1:])
            for name in (
                "arithmeticError", "assertionError", "conversionError", "indexError",
                "libraryError", "nameError", "packageError", "runtimeError",
                "syntaxError", "systemError", "typeError", "uiError", "valueError",
                "vmError",
            )
        },
    }
