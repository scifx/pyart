"""
stdlib.py - Standard library for the mini Arturo interpreter.

The library is *pluggable*: each module is a function that registers
functions on a :class:`evaluator.Library`.  Drop in / drop out at will.
"""
from __future__ import annotations

import math
import re
import sys
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

from . import evaluator as E
from . import parser as P
from . import values as V


class Module:
    """A library module: a named function that registers functions on a library."""

    def __init__(self, name: str, register_fn: Callable[["E.Library"], None]):
        self.name = name
        self.register = register_fn


def load_modules(library: E.Library, modules: List[Module]) -> E.Library:
    for m in modules:
        m.register(library)
    return library


# ===========================================================================
# Helpers (used everywhere below)
# ===========================================================================
def _coerce(v):
    if isinstance(v, float):
        return V.Floating(v)
    if isinstance(v, int) and not isinstance(v, bool):
        return V.Integer(v)
    if isinstance(v, bool):
        return V.Logical(v)
    return V.Floating(float(v))


def _iter(v: V.Value, ctx: Optional[E.Context] = None):
    if isinstance(v, V.VBlock):
        return iter(v.items)
    if isinstance(v, V.VRange):
        return iter(V.Integer(i) for i in v)
    if isinstance(v, V.VString):
        return iter(V.Char(c) for c in v.data)
    if isinstance(v, V.VDictionary):
        # iterate key/value pairs as 2-element blocks
        return iter([V.Block([V.String(k), val]) for k, val in v.items.items()])
    return iter([v])


def _eval_block(blk: V.Value, ctx: E.Context) -> V.Value:
    if not isinstance(blk, V.VBlock):
        return blk
    ev = E.Evaluator(ctx)
    last: V.Value = V.Null()
    for item in blk.items:
        if isinstance(item, V.Value):
            last = ev.eval_expr(item)
        else:
            last = ev.eval_expr(item)
    return last


def _eval_items(blk, ctx):
    """Evaluate every item of a block to a Value."""
    if isinstance(blk, V.VBlock):
        ev = E.Evaluator(ctx)
        out = []
        for item in blk.items:
            if isinstance(item, V.Value):
                out.append(item)
            else:
                out.append(ev.eval_expr(item))
        return out
    return [blk]


def _block_to_value(blk, ctx):
    if isinstance(blk, V.VBlock):
        if not blk.items:
            return V.Null()
        last = V.Null()
        ev = E.Evaluator(ctx)
        for it in blk.items:
            if isinstance(it, V.Value):
                last = it
            else:
                last = ev.eval_expr(it)
        return last
    return blk


def _realize(blk: V.VBlock, ctx: E.Context) -> V.VBlock:
    """Return a copy of ``blk`` whose items are V.Values."""
    ev = E.Evaluator(ctx)
    items = []
    for item in blk.items:
        if isinstance(item, V.Value):
            items.append(item)
        else:
            items.append(ev.eval_expr(item))
    return V.Block(items)


def _convert(tname: str, v: V.Value) -> V.Value:
    if tname == "string":
        if isinstance(v, V.VBlock):
            # Block -> string with space separator
            return V.String(" ".join(V.display(x) for x in _eval_items(v, E.Context(E.Library()))))
        return V.String(V.display(v))
    if tname == "integer":
        return V.Integer(int(float(V.unwrap(v))))
    if tname == "floating":
        return V.Floating(float(V.unwrap(v)))
    if tname == "logical":
        return V.Logical(V.truthy(v))
    if tname == "block":
        if isinstance(v, V.VBlock):
            return v
        return V.Block([v])
    if tname == "char":
        s = str(V.unwrap(v))
        if not s:
            return V.Null()
        return V.Char(s[0])
    if tname == "word":
        return V.Word(V.display(v))
    if tname == "null":
        return V.Null()
    return v


# ===========================================================================
# CORE module
# ===========================================================================
def register_core(lib: E.Library) -> None:
    # Arithmetic ----------------------------------------------------------------
    def add(ctx, args):
        s = sum(V.unwrap(a) for a in args)
        return _coerce(s)

    def sub(ctx, args):
        if not args:
            return V.Integer(0)
        r = V.unwrap(args[0])
        for a in args[1:]:
            r = r - V.unwrap(a)
        return _coerce(r)

    def mul(ctx, args):
        r = 1
        for a in args:
            r *= V.unwrap(a)
        return _coerce(r)

    def div(ctx, args):
        if not args:
            return V.Integer(0)
        r = V.unwrap(args[0])
        for a in args[1:]:
            r = r / V.unwrap(a)
        if all(isinstance(V.unwrap(a), int) and not isinstance(V.unwrap(a), bool)
               for a in args):
            return V.Integer(int(r))
        return V.Floating(float(r))

    def fdiv(ctx, args):
        if not args:
            return V.Floating(0.0)
        r = float(V.unwrap(args[0]))
        for a in args[1:]:
            r = r / V.unwrap(a)
        return V.Floating(r)

    def mod(ctx, args):
        if len(args) < 2:
            return V.Null()
        return _coerce(V.unwrap(args[0]) % V.unwrap(args[1]))

    def divmod_(ctx, args):
        if len(args) < 2:
            return V.Null()
        a, b = V.unwrap(args[0]), V.unwrap(args[1])
        return V.Block([_coerce(a // b), _coerce(a % b)])

    def pow(ctx, args):
        if len(args) < 2:
            return V.Null()
        return _coerce(V.unwrap(args[0]) ** V.unwrap(args[1]))

    def neg(ctx, args):
        if not args:
            return V.Null()
        return _coerce(-V.unwrap(args[0]))

    def inc(ctx, args):
        if not args:
            return V.Null()
        a = args[0]
        if isinstance(a, V.VLiteral):
            cur = ctx.scope.get(a.name, V.Null())
            new = _coerce(V.unwrap(cur) + 1)
            ctx.scope[a.name] = new
            return new
        return _coerce(V.unwrap(a) + 1)

    def dec(ctx, args):
        if not args:
            return V.Null()
        a = args[0]
        if isinstance(a, V.VLiteral):
            cur = ctx.scope.get(a.name, V.Null())
            new = _coerce(V.unwrap(cur) - 1)
            ctx.scope[a.name] = new
            return new
        return _coerce(V.unwrap(a) - 1)

    def abs_(ctx, args):
        if not args:
            return V.Null()
        return _coerce(abs(V.unwrap(args[0])))

    def sign(ctx, args):
        if not args:
            return V.Null()
        v = V.unwrap(args[0])
        if v > 0:
            return V.Integer(1)
        if v < 0:
            return V.Integer(-1)
        return V.Integer(0)

    def sqrt(ctx, args):
        if not args:
            return V.Null()
        return V.Floating(math.sqrt(V.unwrap(args[0])))

    # Bitwise ----------------------------------------------------------------
    def bitand(ctx, args):
        if len(args) < 2:
            return V.Null()
        r = int(V.unwrap(args[0]))
        for a in args[1:]:
            r &= int(V.unwrap(a))
        return V.Integer(r)

    def bitor(ctx, args):
        if len(args) < 2:
            return V.Null()
        r = int(V.unwrap(args[0]))
        for a in args[1:]:
            r |= int(V.unwrap(a))
        return V.Integer(r)

    def bitxor(ctx, args):
        if len(args) < 2:
            return V.Null()
        r = int(V.unwrap(args[0]))
        for a in args[1:]:
            r ^= int(V.unwrap(a))
        return V.Integer(r)

    def bitnot(ctx, args):
        if not args:
            return V.Null()
        return V.Integer(~int(V.unwrap(args[0])))

    def shl(ctx, args):
        if len(args) < 2:
            return V.Null()
        return V.Integer(int(V.unwrap(args[0])) << int(V.unwrap(args[1])))

    def shr(ctx, args):
        if len(args) < 2:
            return V.Null()
        return V.Integer(int(V.unwrap(args[0])) >> int(V.unwrap(args[1])))

    def nand(ctx, args):
        if len(args) < 2:
            return V.Null()
        return V.Integer(~(int(V.unwrap(args[0])) & int(V.unwrap(args[1]))))

    def nor(ctx, args):
        if len(args) < 2:
            return V.Null()
        return V.Integer(~(int(V.unwrap(args[0])) | int(V.unwrap(args[1]))))

    def xnor(ctx, args):
        if len(args) < 2:
            return V.Null()
        return V.Integer(~(int(V.unwrap(args[0])) ^ int(V.unwrap(args[1]))))

    def doubleNegation(ctx, args):
        return V.Integer(int(V.unwrap(args[0])))

    # Comparison ----------------------------------------------------------------
    def equal(ctx, args):
        if len(args) < 2:
            return V.Logical(True)
        return V.Logical(args[0] == args[1])

    def not_equal(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        return V.Logical(args[0] != args[1])

    def less(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        return V.Logical(_cmp(args[0], args[1]) < 0)

    def lessOrEqual(ctx, args):
        if len(args) < 2:
            return V.Logical(True)
        return V.Logical(_cmp(args[0], args[1]) <= 0)

    def greater(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        return V.Logical(_cmp(args[0], args[1]) > 0)

    def greaterOrEqual(ctx, args):
        if len(args) < 2:
            return V.Logical(True)
        return V.Logical(_cmp(args[0], args[1]) >= 0)

    # Logic -------------------------------------------------------------------
    def and_(ctx, args):
        result = True
        for a in args:
            if not V.truthy(a):
                result = False
                break
        return V.Logical(result)

    def or_(ctx, args):
        result = False
        for a in args:
            if V.truthy(a):
                result = True
                break
        return V.Logical(result)

    def not_(ctx, args):
        if not args:
            return V.Logical(True)
        return V.Logical(not V.truthy(args[0]))

    def xor_(ctx, args):
        if len(args) < 2:
            return V.Null()
        return V.Logical(V.truthy(args[0]) != V.truthy(args[1]))

    # Type / conversion ---------------------------------------------------------
    def typeof(ctx, args):
        if not args:
            return V.Null()
        return V.TypeVal(args[0].type_name())

    def to(ctx, args):
        if len(args) < 1:
            return V.Null()
        target = args[0]
        if isinstance(target, V.VType):
            tname = target.name
            value = args[1] if len(args) > 1 else V.Null()
            return _convert(tname, value)
        if isinstance(target, V.VWord):
            tname = target.name
            value = args[1] if len(args) > 1 else V.Null()
            return _convert(tname, value)
        return V.Null()

    def is_(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        # Check if first arg is of the type in second arg
        if isinstance(args[1], V.VType):
            return V.Logical(args[0].type_name() == args[1].name)
        return V.Logical(False)

    # Output --------------------------------------------------------------------
    def print_(ctx, args):
        parts = []
        for a in args:
            if isinstance(a, V.VBlock):
                items = _eval_items(a, ctx)
                parts.append("[" + " ".join(V.display(x) for x in items) + "]")
            else:
                parts.append(V.display(a))
        sys.stdout.write(" ".join(parts) + "\n")
        sys.stdout.flush()
        return V.Null()

    def prints(ctx, args):
        parts = []
        for a in args:
            if isinstance(a, V.VBlock):
                items = _eval_items(a, ctx)
                parts.append("[" + " ".join(V.display(x) for x in items) + "]")
            else:
                parts.append(V.display(a))
        sys.stdout.write(" ".join(parts))
        sys.stdout.flush()
        return V.Null()

    def newline(ctx, args):
        sys.stdout.write("\n")
        sys.stdout.flush()
        return V.Null()

    def color_(ctx, args):
        # Set terminal color (no-op in our minimal impl)
        return V.Null()

    def repeat(ctx, args):
        if len(args) < 2:
            return V.Null()
        s = V.unwrap(args[0])
        n = int(V.unwrap(args[1]))
        if isinstance(args[0], V.VString):
            return V.String(args[0].data * n)
        return V.Null()

    def ensure(ctx, args):
        # ``ensure -> expr`` is sugar for ``if not expr -> print "FAIL"``
        # We just evaluate the expression; for tests we only care about
        # the side effect.
        if args:
            return V.truthy(args[0])
        return False

    def new_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VInteger):
            return V.Integer(v.data)
        if isinstance(v, V.VFloating):
            return V.Floating(v.data)
        if isinstance(v, V.VString):
            return V.String(v.data)
        if isinstance(v, V.VBlock):
            return V.Block(list(v.items))
        if isinstance(v, V.VDictionary):
            return V.Dictionary(OrderedDict(v.items))
        return v

    def info(ctx, args):
        # ``info`` returns metadata about the named function
        if not args:
            return V.Null()
        name = V.display(args[0])
        fn = ctx.library.lookup(name)
        if fn is None:
            fn = ctx.scope.get(name)
        if isinstance(fn, V.VFunction):
            return V.Dictionary(OrderedDict([
                ("name", V.String(fn.name if hasattr(fn, "name") else name)),
                ("args", V.Block([V.String(p) for p in fn.params])),
            ]))
        return V.Null()

    def info_get(ctx, args):
        # ``info.get 'name`` -- returns info as dictionary
        if not args:
            return V.Null()
        name = V.display(args[0])
        return info(ctx, [V.Word(name)])

    # String interpolation
    def render(ctx, args):
        if not args:
            return V.Null()
        s = args[0]
        if not isinstance(s, V.VString):
            return V.Null()
        out: List[str] = []
        i = 0
        text = s.data
        while i < len(text):
            ch = text[i]
            if ch == "|" and i + 1 < len(text) and text[i + 1] == "|":
                out.append("||")
                i += 2
                continue
            if ch == "|":
                end = text.find("|", i + 1)
                if end == -1:
                    out.append(ch)
                    i += 1
                    continue
                expr_str = text[i + 1:end]
                p = P.Parser(expr_str, lib)
                ast = p.parse()
                ctx_local = E.Context(lib)
                ctx_local.scope = dict(ctx.scope)
                ev = E.Evaluator(ctx_local)
                try:
                    v = ev.exec_program(ast) or V.Null()
                except Exception:
                    v = V.Null()
                out.append(V.display(v))
                i = end + 1
                continue
            out.append(ch)
            i += 1
        return V.String("".join(out))

    # Ranges --------------------------------------------------------------------
    def range_fn(ctx, args):
        if len(args) < 2:
            return V.Null()
        start = args[0]
        end = args[1]
        step = args[2] if len(args) > 2 else None
        if (isinstance(start, V.VLiteral) and isinstance(end, V.VLiteral)) or \
           (isinstance(start, V.VChar) and isinstance(end, V.VChar)):
            s_name = start.name if isinstance(start, V.VLiteral) else start.data
            e_name = end.name if isinstance(end, V.VLiteral) else end.data
            s = ord(s_name[0]) if s_name else 0
            e = ord(e_name[0]) if e_name else 0
            return V.Block([V.Char(chr(c)) for c in range(s, e + 1)])
        s = int(V.unwrap(start))
        e = int(V.unwrap(end))
        st = int(V.unwrap(step)) if step is not None else 1
        return V.Range(s, e, st)

    def range3(ctx, args):
        if len(args) < 3:
            return V.Null()
        s = int(V.unwrap(args[0]))
        e = int(V.unwrap(args[1]))
        st = int(V.unwrap(args[2]))
        return V.Range(s, e, st)

    # Array / dictionary --------------------------------------------------------
    def array_(ctx, args):
        if len(args) == 1 and isinstance(args[0], V.VBlock):
            return _realize(args[0], ctx)
        return V.Block(list(args))

    def dictionary_(ctx, args):
        if len(args) == 1 and isinstance(args[0], V.VBlock):
            return _build_dict(args[0], ctx)
        return V.Dictionary(OrderedDict())

    def append(ctx, args):
        if len(args) < 2:
            return V.Null()
        a, b = args[0], args[1]
        if isinstance(a, V.VBlock):
            return V.Block(list(a.items) + [b])
        if isinstance(a, V.VString):
            if isinstance(b, V.VString):
                return V.String(a.data + b.data)
            return V.String(a.data + V.display(b))
        if isinstance(a, V.VDictionary):
            nd = V.Dictionary(OrderedDict(a.items))
            if isinstance(b, V.VDictionary):
                for k, v in b.items.items():
                    nd.items[k] = v
            else:
                nd.items["0"] = b
            return nd
        return V.Null()

    def remove_(ctx, args):
        if len(args) < 2:
            return V.Null()
        a, b = args[0], args[1]
        if isinstance(a, V.VLiteral):
            cur = ctx.scope.get(a.name, V.Null())
            return cur  # alias for `sub`
        if isinstance(a, V.VBlock):
            items = list(a.items)
            if isinstance(b, V.VInteger):
                return V.Block([x for i, x in enumerate(items) if i != b.data])
            return V.Block([x for x in items if x != b])
        if isinstance(a, V.VString):
            if isinstance(b, V.VString):
                return V.String(a.data.replace(b.data, "", 1))
        return V.Null()

    # Basic control flow --------------------------------------------------------
    def do(ctx, args):
        if args and isinstance(args[0], V.VBlock):
            return _eval_block(args[0], ctx)
        return V.Null()

    def if_(ctx, args):
        # Multi-branch: ``if cond [then] [else]``
        if len(args) < 2:
            return V.Null()
        cond = args[0]
        if V.truthy(cond):
            return _exec_branch(args[1], ctx)
        if len(args) >= 3:
            return _eval_block(args[2], ctx)
        return V.Null()

    def switch(ctx, args):
        # ``switch cond [then] [else]`` or just ``cond ? [then] [else]``
        return if_(ctx, args)

    def while_(ctx, args):
        if len(args) < 2:
            return V.Null()
        cond_block, body_block = args[0], args[1]
        last = V.Null()
        while True:
            cond = _block_to_value(cond_block, ctx)
            if not V.truthy(cond):
                break
            last = _eval_block(body_block, ctx)
        return last

    def loop_fn(ctx, args):
        # ``loop collection 'var body``
        if len(args) < 2:
            return V.Null()
        collection = args[0]
        var = args[1] if len(args) > 1 else None
        body = args[2] if len(args) > 2 else args[1]
        var_name = var.name if isinstance(var, V.VLiteral) else None
        if var_name is None:
            return V.Null()
        for item in _iter(collection, ctx):
            saved = ctx.scope.get(var_name)
            ctx.scope[var_name] = item
            try:
                _eval_block(body, ctx)
            finally:
                if saved is not None:
                    ctx.scope[var_name] = saved
                else:
                    ctx.scope.pop(var_name, None)
        return V.Null()

    def loop_with(ctx, args):
        # ``loop.with:'i arr 'x body`` -- loop with index
        # We treat it as a special form: first arg is literal 'i, second is collection.
        if len(args) < 4:
            return V.Null()
        idx_lit = args[0]
        if not isinstance(idx_lit, V.VLiteral):
            return V.Null()
        idx_name = idx_lit.name
        collection = args[1]
        var = args[2]
        body = args[3]
        var_name = var.name if isinstance(var, V.VLiteral) else None
        if var_name is None:
            return V.Null()
        for i, item in enumerate(_iter(collection, ctx)):
            saved_i = ctx.scope.get(idx_name)
            saved_v = ctx.scope.get(var_name)
            ctx.scope[idx_name] = V.Integer(i)
            ctx.scope[var_name] = item
            try:
                _eval_block(body, ctx)
            finally:
                if saved_i is not None:
                    ctx.scope[idx_name] = saved_i
                else:
                    ctx.scope.pop(idx_name, None)
                if saved_v is not None:
                    ctx.scope[var_name] = saved_v
                else:
                    ctx.scope.pop(var_name, None)
        return V.Null()

    def return_(ctx, args):
        val = args[0] if args else V.Null()
        raise E.ReturnSignal(val)

    def break_(ctx, args):
        raise E.BreakSignal()

    def continue_(ctx, args):
        raise E.ContinueSignal()

    # Higher-order ----------------------------------------------------------------
    def map_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        fn = args[1]
        bind_name = None
        if len(args) >= 3 and isinstance(args[1], V.VLiteral):
            bind_name = args[1].name
            fn = args[2]
        elif len(args) >= 3:
            fn = args[2]
        out = []
        for item in _iter(coll, ctx):
            if bind_name:
                saved = ctx.scope.get(bind_name)
                ctx.scope[bind_name] = item
                try:
                    if isinstance(fn, V.VBlock):
                        out.append(_eval_block(fn, ctx))
                    elif isinstance(fn, V.VFunction):
                        out.append(self_call(fn, [item], ctx))
                    else:
                        out.append(fn)
                finally:
                    if saved is not None:
                        ctx.scope[bind_name] = saved
                    else:
                        ctx.scope.pop(bind_name, None)
            else:
                if isinstance(fn, V.VBlock):
                    out.append(_eval_block(fn, ctx))
                elif isinstance(fn, V.VFunction):
                    out.append(self_call(fn, [item], ctx))
                else:
                    out.append(fn)
        return V.Block(out)

    def select_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        fn = args[1]
        bind_name = None
        if len(args) >= 3 and isinstance(args[1], V.VLiteral):
            bind_name = args[1].name
            fn = args[2]
        elif len(args) >= 3:
            fn = args[2]
        out = []
        for item in _iter(coll, ctx):
            if bind_name:
                saved = ctx.scope.get(bind_name)
                ctx.scope[bind_name] = item
                try:
                    if isinstance(fn, V.VBlock):
                        ok = _eval_block(fn, ctx)
                    else:
                        ok = fn
                    if V.truthy(ok):
                        out.append(item)
                finally:
                    if saved is not None:
                        ctx.scope[bind_name] = saved
                    else:
                        ctx.scope.pop(bind_name, None)
            else:
                if isinstance(fn, V.VBlock):
                    ok = _eval_block(fn, ctx)
                else:
                    ok = fn
                if V.truthy(ok):
                    out.append(item)
        return V.Block(out)

    def filter_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        fn = args[1]
        bind_name = None
        if len(args) >= 3 and isinstance(args[1], V.VLiteral):
            bind_name = args[1].name
            fn = args[2]
        elif len(args) >= 3:
            fn = args[2]
        out = []
        for item in _iter(coll, ctx):
            if bind_name:
                saved = ctx.scope.get(bind_name)
                ctx.scope[bind_name] = item
                try:
                    if isinstance(fn, V.VBlock):
                        ok = _eval_block(fn, ctx)
                    else:
                        ok = fn
                    if not V.truthy(ok):
                        out.append(item)
                finally:
                    if saved is not None:
                        ctx.scope[bind_name] = saved
                    else:
                        ctx.scope.pop(bind_name, None)
            else:
                if isinstance(fn, V.VBlock):
                    ok = _eval_block(fn, ctx)
                else:
                    ok = fn
                if not V.truthy(ok):
                    out.append(item)
        return V.Block(out)

    def self_call(fn, args, ctx):
        if not isinstance(fn, V.VFunction):
            return V.Null()
        ev = E.Evaluator(ctx)
        try:
            return ev._call_user_function(fn, args)
        except Exception:
            return V.Null()

    # Helpers --------------------------------------------------------------------
    def size(ctx, args):
        if not args:
            return V.Integer(0)
        v = args[0]
        if isinstance(v, V.VBlock):
            return V.Integer(len(v.items))
        if isinstance(v, V.VString):
            return V.Integer(len(v.data))
        if isinstance(v, V.VDictionary):
            return V.Integer(len(v.items))
        if isinstance(v, V.VRange):
            return V.Integer(len(list(v)))
        if isinstance(v, V.VObject):
            return V.Integer(len(v.fields))
        return V.Integer(0)

    def first_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock) and v.items:
            item = v.items[0]
            if isinstance(item, V.Value):
                return item
            return E.Evaluator(ctx).eval_expr(item)
        if isinstance(v, V.VString) and v.data:
            return V.Char(v.data[0])
        if isinstance(v, V.VRange):
            return V.Integer(v.start)
        return V.Null()

    def last_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock) and v.items:
            item = v.items[-1]
            if isinstance(item, V.Value):
                return item
            return E.Evaluator(ctx).eval_expr(item)
        if isinstance(v, V.VString) and v.data:
            return V.Char(v.data[-1])
        if isinstance(v, V.VRange):
            return V.Integer(v.end)
        return V.Null()

    def get_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        idx = args[1]
        if isinstance(coll, V.VBlock):
            try:
                i = int(V.unwrap(idx))
                if 0 <= i < len(coll.items):
                    item = coll.items[i]
                    if isinstance(item, V.Value):
                        return item
                    return E.Evaluator(ctx).eval_expr(item)
            except (ValueError, IndexError):
                pass
            return V.Null()
        if isinstance(coll, V.VString):
            try:
                return V.Char(coll.data[int(V.unwrap(idx))])
            except (ValueError, IndexError):
                return V.Null()
        if isinstance(coll, V.VDictionary):
            key = str(V.unwrap(idx)) if not isinstance(idx, V.VString) else idx.data
            return coll.items.get(key, V.Null())
        return V.Null()

    def set_(ctx, args):
        if len(args) < 3:
            return V.Null()
        coll = args[0]
        idx = args[1]
        val = args[2]
        if isinstance(coll, V.VBlock):
            try:
                i = int(V.unwrap(idx))
                items = list(coll.items)
                while len(items) <= i:
                    items.append(V.Null())
                items[i] = val
                return V.Block(items)
            except (ValueError, IndexError):
                return V.Null()
        if isinstance(coll, V.VDictionary):
            key = str(V.unwrap(idx)) if not isinstance(idx, V.VString) else idx.data
            coll.items[key] = val
            return coll
        return V.Null()

    def reverse_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock):
            return V.Block(list(reversed(v.items)))
        if isinstance(v, V.VString):
            return V.String(v.data[::-1])
        return V.Null()

    def unique_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock):
            seen = []
            out = []
            for x in v.items:
                if x not in seen:
                    seen.append(x)
                    out.append(x)
            return V.Block(out)
        return V.Null()

    def sort_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock):
            items = list(v.items)
            try:
                return V.Block(sorted(items, key=_sort_key))
            except TypeError:
                return V.Block(items)
        if isinstance(v, V.VString):
            return V.String("".join(sorted(v.data)))
        return V.Null()

    def contains_(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        coll, item = args[0], args[1]
        if isinstance(coll, V.VBlock):
            return V.Logical(item in coll.items)
        if isinstance(coll, V.VString):
            return V.Logical(V.unwrap(item) in coll.data)
        if isinstance(coll, V.VDictionary):
            key = item.name if isinstance(item, V.VWord) else (
                item.data if isinstance(item, V.VString) else str(V.unwrap(item))
            )
            return V.Logical(key in coll.items)
        return V.Logical(False)

    def in_(ctx, args):
        return contains_(ctx, list(reversed(args)))

    def split_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VString):
            return V.Block([V.Char(c) for c in v.data.split()])
        return V.Null()

    def join_(ctx, args):
        if not args:
            return V.Null()
        if len(args) == 2 and isinstance(args[0], V.VString) and isinstance(args[1], V.VBlock):
            sep = args[0].data
            block = args[1]
            items = _eval_items(block, ctx)
            parts = []
            for it in items:
                if isinstance(it, V.VChar):
                    parts.append(it.data)
                elif isinstance(it, V.VString):
                    parts.append(it.data)
                else:
                    parts.append(V.display(it))
            return V.String(sep.join(parts))
        if len(args) == 1 and isinstance(args[0], V.VBlock):
            items = _eval_items(args[0], ctx)
            parts = []
            for it in items:
                if isinstance(it, V.VChar):
                    parts.append(it.data)
                elif isinstance(it, V.VString):
                    parts.append(it.data)
                else:
                    parts.append(V.display(it))
            return V.String("".join(parts))
        return V.Null()

    def upper_(ctx, args):
        if args and isinstance(args[0], V.VString):
            return V.String(args[0].data.upper())
        return V.Null()

    def lower_(ctx, args):
        if args and isinstance(args[0], V.VString):
            return V.String(args[0].data.lower())
        return V.Null()

    def capitalize_(ctx, args):
        if args and isinstance(args[0], V.VString):
            return V.String(args[0].data.capitalize())
        return V.Null()

    def prefix_(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        if isinstance(args[0], V.VString) and isinstance(args[1], V.VString):
            return V.Logical(args[0].data.startswith(args[1].data))
        return V.Logical(False)

    def suffix_(ctx, args):
        if len(args) < 2:
            return V.Logical(False)
        if isinstance(args[0], V.VString) and isinstance(args[1], V.VString):
            return V.Logical(args[0].data.endswith(args[1].data))
        return V.Logical(False)

    def odd_(ctx, args):
        if not args:
            return V.Null()
        return V.Logical(bool(int(V.unwrap(args[0])) % 2))

    def even_(ctx, args):
        if not args:
            return V.Null()
        return V.Logical(bool(int(V.unwrap(args[0])) % 2 == 0))

    def prime_(ctx, args):
        if not args:
            return V.Null()
        n = int(V.unwrap(args[0]))
        if n < 2:
            return V.Logical(False)
        for i in range(2, int(n ** 0.5) + 1):
            if n % i == 0:
                return V.Logical(False)
        return V.Logical(True)

    def factorial_(ctx, args):
        if not args:
            return V.Null()
        n = int(V.unwrap(args[0]))
        r = 1
        for i in range(2, n + 1):
            r *= i
        return V.Integer(r)

    def fibonacci_(ctx, args):
        if not args:
            return V.Null()
        n = int(V.unwrap(args[0]))
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return V.Integer(a)

    def take_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        n = int(V.unwrap(args[1]))
        if isinstance(coll, V.VBlock):
            return V.Block(coll.items[:n])
        if isinstance(coll, V.VRange):
            return V.Block(list(coll)[:n])
        return V.Null()

    def drop_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        n = int(V.unwrap(args[1]))
        if isinstance(coll, V.VBlock):
            return V.Block(coll.items[n:])
        return V.Null()

    def slice_(ctx, args):
        if len(args) < 3:
            return V.Null()
        coll = args[0]
        s = int(V.unwrap(args[1]))
        e = int(V.unwrap(args[2]))
        if isinstance(coll, V.VBlock):
            return V.Block(coll.items[s:e+1])
        return V.Null()

    def permutate_(ctx, args):
        if not args:
            return V.Null()
        coll = args[0]
        if isinstance(coll, V.VBlock):
            from itertools import permutations
            items = list(coll.items)
            perms = list(permutations(items))
            return V.Block([V.Block(list(p)) for p in perms])
        return V.Null()

    def shuffle_(ctx, args):
        if not args:
            return V.Null()
        import random
        coll = args[0]
        if isinstance(coll, V.VBlock):
            items = list(coll.items)
            random.shuffle(items)
            return V.Block(items)
        return V.Null()

    def repeat_(ctx, args):
        if len(args) < 2:
            return V.Null()
        coll = args[0]
        n = int(V.unwrap(args[1]))
        if isinstance(coll, V.VBlock):
            items = list(coll.items)
            return V.Block(items * n)
        return V.Null()

    def sum_(ctx, args):
        if not args:
            return V.Integer(0)
        v = args[0]
        if isinstance(v, V.VBlock):
            s = 0
            for x in v.items:
                if isinstance(x, V.Value):
                    s += V.unwrap(x)
            return _coerce(s)
        return V.Null()

    def average_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock):
            items = [V.unwrap(x) if isinstance(x, V.Value) else 0 for x in v.items]
            if not items:
                return V.Null()
            return _coerce(sum(items) / len(items))
        return V.Null()

    def minimum_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock) and v.items:
            try:
                return min(v.items, key=_sort_key)
            except TypeError:
                return v.items[0]
        return V.Null()

    def maximum_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock) and v.items:
            try:
                return max(v.items, key=_sort_key)
            except TypeError:
                return v.items[0]
        return V.Null()

    def inspect_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock):
            print("== BLOCK ==")
            for i, item in enumerate(v.items):
                print(f"  [{i}] {V.display(item)}")
        else:
            print(f"== {v.kind.value} ==")
            print(f"  {V.display(v)}")
        return V.Null()

    def express_(ctx, args):
        if not args:
            return V.Null()
        v = args[0]
        if isinstance(v, V.VBlock):
            return V.String("[" + " ".join(V.display(x) for x in v.items) + "]")
        return V.String(V.display(v))

    def now_(ctx, args):
        import datetime
        return V.Date(iso=datetime.datetime.now().isoformat())

    def to_intrepid_(ctx, args):
        # Alias for now (no-op).
        return args[0] if args else V.Null()

    # ---------------- Register everything ---------------------------------------
    lib.register("add", -1, add)
    lib.register("sub", -1, sub)
    lib.register("mul", -1, mul)
    lib.register("div", -1, div)
    lib.register("fdiv", -1, fdiv)
    lib.register("mod", 2, mod)
    lib.register("divmod", 2, divmod_)
    lib.register("pow", 2, pow)
    lib.register("neg", 1, neg)
    lib.register("inc", 1, inc)
    lib.register("dec", 1, dec)
    lib.register("abs", 1, abs_)
    lib.register("sign", 1, sign)
    lib.register("sqrt", 1, sqrt)
    lib.register("and", -1, bitand)
    lib.register("or", -1, bitor)
    lib.register("xor", -1, bitxor)
    lib.register("not", 1, bitnot)
    lib.register("shl", 2, shl)
    lib.register("shr", 2, shr)
    lib.register("nand", 2, nand)
    lib.register("nor", 2, nor)
    lib.register("xnor", 2, xnor)
    lib.register("doubleNegation", 1, doubleNegation)
    lib.register("equal?", 2, equal)
    lib.register("notEqual?", 2, not_equal)
    lib.register("less?", 2, less)
    lib.register("lessOrEqual?", 2, lessOrEqual)
    lib.register("greater?", 2, greater)
    lib.register("greaterOrEqual?", 2, greaterOrEqual)
    lib.register("and?", -1, and_)
    lib.register("or?", -1, or_)
    lib.register("not?", 1, not_)
    lib.register("xor?", 2, xor_)
    lib.register("type", 1, typeof)
    lib.register("to", -1, to)
    lib.register("is?", 2, is_)
    lib.register("print", -1, print_)
    lib.register("prints", -1, prints)
    lib.register("newline", 0, newline)
    lib.register("color", 1, color_)
    lib.register("repeat", -1, repeat)
    lib.register("ensure", -1, ensure)
    lib.register("new", 1, new_)
    lib.register("info", -1, info)
    lib.register("info.get", -1, info_get)
    lib.register("render", 1, render)
    lib.register("range", -1, range_fn)
    lib.register("range3", 3, range3)
    lib.register("array", -1, array_)
    lib.register("dictionary", -1, dictionary_)
    lib.register("append", 2, append)
    lib.register("remove", 2, remove_)
    lib.register("do", 1, do)
    lib.register("if", -1, if_)
    lib.register("switch", -1, switch)
    lib.register("while", 2, while_)
    lib.register("loop", -1, loop_fn)
    lib.register("loop.with", -1, loop_with)
    lib.register("return", -1, return_)
    lib.register("break", 0, break_)
    lib.register("continue", 0, continue_)
    lib.register("map", -1, map_)
    lib.register("select", -1, select_)
    lib.register("filter", -1, filter_)
    lib.register("size", 1, size)
    lib.register("first", 1, first_)
    lib.register("last", 1, last_)
    lib.register("get", 2, get_)
    lib.register("set", 3, set_)
    lib.register("reverse", 1, reverse_)
    lib.register("unique", 1, unique_)
    lib.register("sort", 1, sort_)
    lib.register("contains?", 2, contains_)
    lib.register("in?", 2, in_)
    lib.register("split", -1, split_)
    lib.register("join", -1, join_)
    lib.register("upper", 1, upper_)
    lib.register("lower", 1, lower_)
    lib.register("capitalize", 1, capitalize_)
    lib.register("prefix?", 2, prefix_)
    lib.register("suffix?", 2, suffix_)
    lib.register("odd?", 1, odd_)
    lib.register("even?", 1, even_)
    lib.register("prime?", 1, prime_)
    lib.register("factorial", 1, factorial_)
    lib.register("fibonacci", 1, fibonacci_)
    lib.register("take", 2, take_)
    lib.register("drop", 2, drop_)
    lib.register("slice", 3, slice_)
    lib.register("permutate", 1, permutate_)
    lib.register("shuffle", 1, shuffle_)
    lib.register("sum", 1, sum_)
    lib.register("average", 1, average_)
    lib.register("minimum", 1, minimum_)
    lib.register("maximum", 1, maximum_)
    lib.register("inspect", 1, inspect_)
    lib.register("express", 1, express_)
    lib.register("now", 0, now_)
    lib.register("to.intrepid", 1, to_intrepid_)
    # Aliases for infix operators
    lib.alias("+", "add")
    lib.alias("-", "sub")
    lib.alias("*", "mul")
    lib.alias("/", "div")
    lib.alias("//", "fdiv")
    lib.alias("%", "mod")
    lib.alias("^", "pow")
    lib.alias("**", "pow")
    lib.alias("=", "equal?")
    lib.alias("==", "equal?")
    lib.alias("<>", "notEqual?")
    lib.alias("<", "less?")
    lib.alias("<=", "lessOrEqual?")
    lib.alias("=<", "lessOrEqual?")
    lib.alias(">", "greater?")
    lib.alias(">=", "greaterOrEqual?")
    lib.alias("&", "and?")
    lib.alias("|", "or?")
    lib.alias("++", "append")
    lib.alias("--", "remove")
    lib.alias("?", "switch")
    lib.alias("@", "array")
    lib.alias("#", "dictionary")
    lib.alias("..", "range")
    lib.alias("...", "range3")
    lib.alias("~", "render")
    lib.alias("!!", "doubleNegation")
    lib.alias("!", "not?")


# ===========================================================================
# IO module
# ===========================================================================
def register_io(lib: E.Library) -> None:
    lib.alias("print", "print")
    lib.alias("prints", "prints")


# ===========================================================================
# Default modules
# ===========================================================================
DEFAULT_MODULES: List[Module] = [
    Module("core", register_core),
    Module("io", register_io),
]


# ===========================================================================
# Helpers used in core
# ===========================================================================
def _cmp(a: V.Value, b: V.Value) -> int:
    if isinstance(a, (V.VInteger, V.VFloating)) and isinstance(b, (V.VInteger, V.VFloating)):
        return (V.unwrap(a) > V.unwrap(b)) - (V.unwrap(a) < V.unwrap(b))
    if isinstance(a, V.VString) and isinstance(b, V.VString):
        return (a.data > b.data) - (a.data < b.data)
    sa = V.display(a)
    sb = V.display(b)
    return (sa > sb) - (sa < sb)


def _sort_key(v: V.Value):
    if isinstance(v, V.VInteger):
        return (0, v.data)
    if isinstance(v, V.VFloating):
        return (1, v.data)
    if isinstance(v, V.VString):
        return (2, v.data)
    if isinstance(v, V.VChar):
        return (3, v.data)
    return (4, V.display(v))


def _build_dict(block: V.VBlock, ctx: E.Context) -> V.VDictionary:
    """Build a dictionary from a block by walking it left-to-right and
    collecting label-value pairs (label followed by some value)."""
    d: "OrderedDict[str, V.Value]" = OrderedDict()
    items = _eval_items(block, ctx)
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, V.VLabel):
            name = item.name
            i += 1
            value = items[i] if i < len(items) else V.Null()
            d[name] = value
            i += 1
        else:
            i += 1
    return V.Dictionary(OrderedDict(d))
