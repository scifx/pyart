"""
iterators.py - loop / map / select / filter / fold / arrange and friends.

Arturo iterators all share the same shape::

    <iterator> collection params action

where ``params`` is a :literal (``'x``), a block of names (``[k v]``), an
inline block, ``ø``/``null`` for "no parameters".  The ``.with:`` attribute
injects an index (or key) parameter.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import List, Optional

from .. import values as V
from ..evaluator import ArturoError, BreakSignal, ContinueSignal, MISSING, ReturnSignal
from . import *
from . import (VOID, attr, attr_true, collection_size, fail, impl, is_num,
               num_result, range_values, seq_of, to_int, to_number)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextmanager
def protected(ev, names):
    """Protect (and later restore) the given symbol names."""
    saved = {}
    for name in names:
        if name not in saved:
            saved[name] = ev.ctx.syms.get(name, MISSING)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is MISSING:
                ev.ctx.syms.pop(name, None)
            else:
                ev.ctx.syms[name] = value


def param_names(params: V.Value) -> List[str]:
    """Extract iterator parameter names from the ``params`` argument."""
    if params is None:
        return []
    if isinstance(params, V.Null) or params.kind == "null":
        return []
    if isinstance(params, V.Symbol) and params.data in ("ø", "∅"):
        return []
    if isinstance(params, V.Literal):
        return [params.data]
    if isinstance(params, V.Word):
        return [params.data]
    if isinstance(params, V.Block):
        out = []
        for item in params.data:
            if isinstance(item, (V.Word, V.Literal)):
                out.append(item.data)
            elif isinstance(item, V.Label):
                out.append(item.data)
            elif isinstance(item, V.Symbol) and item.data in ("ø", "∅"):
                continue
            elif isinstance(item, V.Null):
                continue
        return out
    return []


class IntSeq:
    """Lazy ``list``-like sequence of Integers for ranges (avoids materialising)."""

    __slots__ = ("_range",)

    def __init__(self, rng):
        self._range = rng

    def __iter__(self):
        Integer = V.Integer
        for i in self._range:
            yield Integer(i)

    def __len__(self):
        return len(self._range)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [V.Integer(i) for i in self._range[index]]
        return V.Integer(self._range[index])

    def __reversed__(self):
        Integer = V.Integer
        for i in reversed(self._range):
            yield Integer(i)


def iter_values(ev, collection: V.Value, nparams: int = 1) -> List[V.Value]:
    """Expand the iterable into a list of item-values.

    With ``nparams >= 2`` dictionaries yield ``key`` + ``value`` inside a
    block so that ``loop dict [k v][...]`` works.
    """
    k = collection.kind
    if k == "range":
        return IntSeq(range_values(collection))
    if k in ("block", "inline"):
        return list(collection.data)
    if k == "integer":
        return [V.Integer(i) for i in range(1, collection.data + 1)]
    if k == "string":
        return [V.Char(c) for c in collection.data]
    if k == "dictionary":
        if nparams >= 2:
            return [V.Block([V.String(key), val]) for key, val in collection.data.items()]
        return list(collection.data.values())
    if k == "object":
        if nparams >= 2:
            return [V.Block([V.String(key), val]) for key, val in collection.data.items()]
        return list(collection.data.values())
    if k == "binary":
        return [V.Integer(b) for b in collection.data]
    if k == "null":
        return []
    fail(f"cannot iterate over {k}", "Type Error")


def _apply_item(ev, names: List[str], item: V.Value, index: Optional[str], i: int) -> None:
    if len(names) == 1:
        ev.ctx.set(names[0], item)
    elif len(names) >= 2:
        parts = item.data if isinstance(item, V.Block) else [item]
        for idx, val in enumerate(parts):
            if idx < len(names):
                ev.ctx.set(names[idx], val)
    if index is not None:
        ev.ctx.set(index, V.Integer(i))


def _is_pair(item: V.Value) -> bool:
    return False


def _counter_index(ev, counter) -> Optional[str]:
    if counter is None:
        return None
    if isinstance(counter, V.Literal):
        return counter.data
    if isinstance(counter, V.Word):
        return counter.data
    if isinstance(counter, V.Block) and counter.data:
        first = counter.data[0]
        if isinstance(first, (V.Literal, V.Word)):
            return first.data
    if isinstance(counter, V.Block) and len(counter.data) >= 2:
        first = counter.data[0]
        if isinstance(first, (V.Literal, V.Word)):
            return first.data
    return None


def _run(ev, args, mode: str):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    counter = attr(ev, "with", None)
    index_name = _counter_index(ev, counter)
    forever = attr_true(ev, "forever")

    if not isinstance(action, V.Block) and mode != "loop":
        fail("action must be a block", "Type Error")

    items = iter_values(ev, collection, len(names) if names else 1)
    protect = list(names) + ([index_name] if index_name else [])

    results: List[V.Value] = []
    last: V.Value = V.NULL

    with protected(ev, protect):
        i = 0
        while True:
            if i >= len(items):
                if not forever or not items:
                    break
                i = 0
            item = items[i]
            _apply_item(ev, names, item, index_name, i)
            try:
                if mode == "loop":
                    value = ev.do_block_unscoped(action)
                else:
                    value = ev.do_block(action)
            except BreakSignal:
                break
            except ContinueSignal:
                i += 1
                continue
            last = value
            if mode == "map":
                results.append(value)
            elif mode == "select":
                if V.is_true(value):
                    results.append(item)
            elif mode == "filter":
                if V.is_true(value):
                    results.append(item)
            i += 1

    if mode == "map" or mode == "select" or mode == "filter":
        return V.Block(results)
    return last


def iter_loop(ev, args):
    return _run(ev, args, "loop")


@impl("loop")
def _loop(ev, args):
    return _run(ev, args, "loop")


@impl("map")
def _map(ev, args):
    return _run(ev, args, "map")


@impl("select")
def _select(ev, args):
    nth = attr(ev, "n", None)
    if nth is not None:
        collection, params, action = args[0], args[1], args[2]
        names = param_names(params)
        items = iter_values(ev, collection, len(names) if names else 1)
        want = to_int(nth)
        found = 0
        with protected(ev, names):
            for i, item in enumerate(items):
                _apply_item(ev, names, item, None, i)
                if V.is_true(ev.do_block(action)):
                    found += 1
                    if found == want:
                        return item
        return VOID
    first = attr(ev, "first", None)
    last = attr(ev, "last", None)
    if first is None and last is None:
        return _run(ev, args, "select")
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    items = iter_values(ev, collection, len(names) if names else 1)
    protect = list(names)
    selected: List[V.Value] = []
    want = 0
    if first is not None:
        want = 1 if (first.kind == "logical") else to_int(first)
    elif last is not None:
        want = 1 if (last.kind == "logical") else to_int(last)

    if first is not None:
        with protected(ev, protect):
            for i, item in enumerate(items):
                _apply_item(ev, names, item, None, i)
                if V.is_true(ev.do_block(action)):
                    selected.append(item)
                    if len(selected) >= want:
                        break
        return V.Block(selected)

    with protected(ev, protect):
        for i, item in enumerate(items):
            _apply_item(ev, names, item, None, i)
            if V.is_true(ev.do_block(action)):
                selected.append(item)
                if len(selected) > want:
                    selected.pop(0)
    return V.Block(selected)
    return selected[0] if selected else VOID


@impl("filter")
def _filter(ev, args):
    return _run(ev, args, "filter")


@impl("fold")
def _fold(ev, args):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    seed = attr(ev, "seed", MISSING)
    right = attr_true(ev, "right")
    items = iter_values(ev, collection, len(names) if names else 1)
    if right:
        items = list(reversed(items))

    if seed is MISSING:
        if not items:
            return VOID
        acc = items[0]
        items = items[1:]
    else:
        acc = seed

    with protected(ev, names):
        for i, item in enumerate(items):
            if len(names) >= 2:
                ev.ctx.set(names[0], acc)
                _apply_item(ev, names[1:], item, None, i)
            elif names:
                ev.ctx.set(names[0], acc)
            try:
                acc = ev.do_block(action)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
    return acc


@impl("arrange")
def _arrange(ev, args):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    items = iter_values(ev, collection, len(names) if names else 1)
    out: List[V.Value] = []
    with protected(ev, names):
        for i, item in enumerate(items):
            _apply_item(ev, names, item, None, i)
            try:
                if mode == "loop":
                    value = ev.do_block_unscoped(action)
                else:
                    value = ev.do_block(action)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
            if value is VOID:
                continue
            out.append(value)
    return V.Block(out)


@impl("collect")
def _collect(ev, args):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    items = iter_values(ev, collection, len(names) if names else 1)
    out: List[V.Value] = []
    with protected(ev, names):
        for i, item in enumerate(items):
            _apply_item(ev, names, item, None, i)
            try:
                if mode == "loop":
                    value = ev.do_block_unscoped(action)
                else:
                    value = ev.do_block(action)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
            out.append(value)
    return V.Block(out)


@impl("gather")
def _gather(ev, args):
    return _collect(ev, args)


@impl("every?")
def _every(ev, args):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    items = iter_values(ev, collection, len(names) if names else 1)
    with protected(ev, names):
        for i, item in enumerate(items):
            _apply_item(ev, names, item, None, i)
            if not V.is_true(ev.do_block(action)):
                return V.Logical(False)
    return V.Logical(True)


@impl("some?")
def _some(ev, args):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    items = iter_values(ev, collection, len(names) if names else 1)
    with protected(ev, names):
        for i, item in enumerate(items):
            _apply_item(ev, names, item, None, i)
            if V.is_true(ev.do_block(action)):
                return V.Logical(True)
    return V.Logical(False)


# ---------------------------------------------------------------------------
# chunk / cluster / enumerate / combine
# ---------------------------------------------------------------------------
@impl("chunk")
def _chunk(ev, args):
    collection, params, action = args[0], args[1], args[2]
    names = param_names(params)
    items = iter_values(ev, collection)
    size = attr(ev, "size", None)
    if size is not None:
        n = to_int(size)
        return V.Block([V.Block(items[i:i + n]) for i in range(0, len(items), n)])
    out: List[V.Value] = []
    current_key = None
    current: List[V.Value] = []
    with protected(ev, names):
        for item in items:
            ev.ctx.set(names[0], item) if names else None
            key = ev.do_block(action)
            if current_key is None or V.same_value(key, current_key):
                current.append(item)
            else:
                out.append(V.Block(current))
                current = [item]
            current_key = key
    if current:
        out.append(V.Block(current))
    return V.Block(out)


@impl("cluster")
def _cluster(ev, args):
    return _chunk(ev, args)


@impl("enumerate")
def _enumerate(ev, args):
    collection, params = args[0], args[1]
    names = param_names(params)
    count = args[2]
    items = iter_values(ev, collection)
    n = to_int(count) if count is not None else 2
    out = []
    for i in range(0, len(items), n):
        chunk = items[i:i + n]
        out.append(V.Block(chunk))
    return V.Block(out)


@impl("combine")
def _combine(ev, args):
    a, b = args[0], args[1]
    left = seq_of(a) if a.kind not in ("block", "inline") else list(a.data)
    right = seq_of(b) if b.kind not in ("block", "inline") else list(b.data)
    out = []
    for i in range(max(len(left), len(right))):
        x = left[i] if i < len(left) else V.NULL
        y = right[i] if i < len(right) else V.NULL
        out.append(V.Block([x, y]))
    return V.Block(out)


@impl("couple")
def _couple(ev, args):
    a, b = args[0], args[1]
    left = list(a.data) if a.kind in ("block", "inline") else [a]
    right = list(b.data) if b.kind in ("block", "inline") else [b]
    return V.Block([V.Block([x, y]) for x, y in zip(left, right)])


@impl("decouple")
def _decouple(ev, args):
    block = args[0]
    if not isinstance(block, V.Block) or len(block.data) < 2:
        return V.Block([block])
    return V.Block([block.data[0], block.data[1]])


# ---------------------------------------------------------------------------
# Convenience aggregators
# ---------------------------------------------------------------------------
def _aggregate(ev, args, fn):
    values = args[0]
    if values.kind in ("block", "inline"):
        items = list(values.data)
    elif values.kind == "dictionary":
        items = list(values.data.values())
    elif values.kind == "range":
        items = [V.Integer(i) for i in range_values(values)]
    else:
        items = [values]
    if not items:
        return V.Integer(0)
    return fn(items)


@impl("sum")
def _sum(ev, args):
    def total(items):
        acc = items[0]
        for item in items[1:]:
            if is_num(acc) and is_num(item):
                acc = num_result(to_number(acc) + to_number(item))
            else:
                acc = _concat(acc, item)
        return acc

    return _aggregate(ev, args, total)


def _concat(a, b):
    if a.kind == "string":
        return V.String(a.data + V.to_string(b))
    if a.kind in ("block", "inline"):
        return V.Block(a.data + (b.data if isinstance(b, V.Block) else [b]))
    return V.String(V.to_string(a) + V.to_string(b))


@impl("product")
def _product(ev, args):
    def prod(items):
        acc = items[0]
        for item in items[1:]:
            acc = num_result(to_number(acc) * to_number(item))
        return acc

    return _aggregate(ev, args, prod)


@impl("average")
def _average(ev, args):
    def mean(items):
        total = 0
        for item in items:
            total += to_number(item)
        return num_result(total / len(items)) if isinstance(total, int) else V.Floating(total / len(items))

    return _aggregate(ev, args, mean)


@impl("maximum")
def _maximum(ev, args):
    from . import compare

    def mx(items):
        best = items[0]
        for item in items[1:]:
            if compare(item, best) > 0:
                best = item
        return best

    return _aggregate(ev, args, mx)


@impl("minimum")
def _minimum(ev, args):
    from . import compare

    def mn(items):
        best = items[0]
        for item in items[1:]:
            if compare(item, best) < 0:
                best = item
        return best

    return _aggregate(ev, args, mn)


@impl("min")
def _min(ev, args):
    from . import compare

    value = args[0]
    items = value.data if isinstance(value, V.Block) else [value]
    if not items:
        return V.NULL
    best = items[0]
    for item in items[1:]:
        if compare(item, best) < 0:
            best = item
    return best


@impl("max")
def _max(ev, args):
    from . import compare

    value = args[0]
    items = value.data if isinstance(value, V.Block) else [value]
    if not items:
        return V.NULL
    best = items[0]
    for item in items[1:]:
        if compare(item, best) > 0:
            best = item
    return best
