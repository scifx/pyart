"""
collections.py - blocks, dictionaries, ranges and the operations on them.
"""
from __future__ import annotations

import random as _random
from typing import List

from .. import values as V
from ..evaluator import ArturoError, MISSING
from . import *
from . import (VOID, attr, attr_true, collection_size, compare, fail, impl,
               inplace, is_num, num_result, range_values, seq_of, to_int, to_number)


# ---------------------------------------------------------------------------
# Access helpers (used by the evaluator for `a\b` paths)
# ---------------------------------------------------------------------------
def get_value(ev, container: V.Value, key: V.Value) -> V.Value:
    if isinstance(key, V.Char):
        key = V.String(key.data)
    if isinstance(key, (V.Literal, V.Word)):
        name = key.data
    elif isinstance(key, V.String):
        name = key.data
    else:
        name = None

    k = container.kind
    if k in ("dictionary", "object"):
        if name is not None:
            if name in container.data:
                return container.data[name]
            raise ArturoError("Key Error", f"Key not found: {name}")
        text = V.to_string(key)
        if text in container.data:
            return container.data[text]
        raise ArturoError("Key Error", f"Key not found: {text}")
    if k in ("block", "inline"):
        index = to_int(key)
        n = len(container.data)
        if index < 0:
            index += n
        if index < 0 or index >= n:
            raise ArturoError("Index Error", f"Index out of bounds: {to_int(key)}")
        return container.data[index]
    if k == "string":
        index = to_int(key)
        n = len(container.data)
        if index < 0:
            index += n
        if index < 0 or index >= n:
            raise ArturoError("Index Error", f"Index out of bounds: {to_int(key)}")
        return V.Char(container.data[index])
    if k == "date":
        from .. import nimtime

        field = nimtime.attribute(container, name if name is not None else V.to_string(key))
        if field is None:
            raise ArturoError("Key Error", f"Key not found: {V.to_string(key)}")
        if isinstance(field, bool):
            return V.Logical(field)
        if isinstance(field, int):
            return V.Integer(field)
        if isinstance(field, str):
            return V.String(field)
        return V.Date(field)
    if k == "range":
        values = [V.Integer(i) for i in range_values(container)]
        index = to_int(key)
        if index < 0:
            index += len(values)
        if 0 <= index < len(values):
            return values[index]
        raise ArturoError("Index Error", f"Index out of bounds: {to_int(key)}")
    if k == "binary":
        index = to_int(key)
        return V.Integer(container.data[index])
    fail(f"cannot get from {k}", "Type Error")


def set_value(ev, container: V.Value, key: V.Value, value: V.Value) -> None:
    k = container.kind
    if k in ("dictionary", "object"):
        name = key.data if isinstance(key, (V.Literal, V.Word, V.String)) else V.to_string(key)
        container.data[name] = value
        return
    if k in ("block", "inline"):
        index = to_int(key)
        n = len(container.data)
        if index < 0:
            index += n
        if index < 0 or index >= n:
            raise ArturoError("Index Error", f"Index out of bounds: {to_int(key)}")
        container.data[index] = value
        return
    fail(f"cannot set into {k}", "Type Error")


# ---------------------------------------------------------------------------
# append / remove / insert / prepend / concat
# ---------------------------------------------------------------------------
@impl("append")
def _append(ev, args):
    target, value = args[0], args[1]
    setter = None
    target, setter = inplace(ev, target)

    result = None
    if target.kind in ("block", "inline"):
        if isinstance(value, V.Block) and not isinstance(target, V.Inline):
            target.data.extend(value.data)
        else:
            target.data.append(value)
        result = target
    elif target.kind == "string":
        target.data = target.data + V.to_string(value)
        result = target
    elif target.kind == "char":
        result = V.String(target.data + V.to_string(value))
    elif target.kind == "dictionary":
        target.data.update(value.data if value.kind == "dictionary" else {})
        result = target
    elif target.kind == "binary":
        if value.kind == "binary":
            target.data = target.data + value.data
        else:
            target.data = target.data + bytes([to_int(value)])
        result = target
    else:
        fail(f"cannot append to {target.kind}", "Type Error")

    if setter:
        setter(result)
    return result


@builtin("remove", arity=2, attrs=["index", "key", "prefix", "suffix", "once"])
def _remove(ev, args):
    target, value = args[0], args[1]
    setter = None
    target, setter = inplace(ev, target)

    if attr_true(ev, "key") and target.kind in ("dictionary", "object"):
        key = value.data if isinstance(value, (V.Literal, V.Word, V.String)) else V.to_string(value)
        target.data.pop(key, None)
        if setter:
            setter(target)
        return target

    index = attr(ev, "index", None)
    if index is not None and target.kind in ("block", "inline"):
        i = to_int(value)
        if 0 <= i < len(target.data):
            del target.data[i]
        if setter:
            setter(target)
        return target

    if target.kind in ("block", "inline"):
        if isinstance(value, V.Block):
            for item in value.data:
                for i, existing in enumerate(target.data):
                    if V.same_value(existing, item):
                        del target.data[i]
                        break
        else:
            for i, existing in enumerate(target.data):
                if V.same_value(existing, value):
                    del target.data[i]
                    break
        result = target
    elif target.kind == "dictionary":
        key = value.data if isinstance(value, (V.Literal, V.Word, V.String)) else V.to_string(value)
        target.data.pop(key, None)
        result = target
    elif target.kind == "string":
        text = target.data
        if isinstance(value, V.Block):
            for item in value.data:
                text = text.replace(V.to_string(item), "")
        else:
            text = text.replace(V.to_string(value), "")
        target.data = text
        result = target
    else:
        fail(f"cannot remove from {target.kind}", "Type Error")

    if setter:
        setter(result)
    return result


@impl("insert")
def _insert(ev, args):
    collection, index, value = args
    setter = None
    collection, setter = inplace(ev, collection)
    if collection.kind not in ("block", "inline"):
        fail("cannot insert into non-block", "Type Error")
    idx = to_int(index)
    collection.data.insert(idx, value)
    if setter:
        setter(collection)
    return collection


@impl("prepend")
def _prepend(ev, args):
    collection, value = args
    setter = None
    collection, setter = inplace(ev, collection)
    if collection.kind in ("block", "inline"):
        if isinstance(value, V.Block):
            collection.data[0:0] = value.data
        else:
            collection.data.insert(0, value)
        result = collection
    elif collection.kind == "string":
        result = V.String(V.to_string(value) + collection.data)
    else:
        fail("cannot prepend to non-collection", "Type Error")
    if setter:
        setter(result)
    return result


# ---------------------------------------------------------------------------
# size / first / last / keys / values
# ---------------------------------------------------------------------------
@impl("size")
def _size(ev, args):
    value = args[0]
    if value.kind == "integer":
        return V.Integer(1)
    if value.kind == "range":
        return V.Integer(len(range_values(value)))
    return V.Integer(collection_size(value))


@impl("first")
def _first(ev, args):
    value = args[0]
    n = attr(ev, "n", None)
    if n is not None:
        count = to_int(n)
        if value.kind == "string":
            return V.String(value.data[:count])
        return V.Block(_items_of(ev, value)[:count])
    items = _items_of(ev, value)
    if not items:
        return V.NULL
    return items[0]


@impl("last")
def _last(ev, args):
    value = args[0]
    n = attr(ev, "n", None)
    if n is not None:
        count = to_int(n)
        if value.kind == "string":
            return V.String(value.data[-count:] if count else "")
        return V.Block(_items_of(ev, value)[-count:] if count else [])
    items = _items_of(ev, value)
    if not items:
        return V.NULL
    return items[-1]


def _items_of(ev, value: V.Value) -> List[V.Value]:
    k = value.kind
    if k in ("block", "inline"):
        return value.data
    if k == "string":
        return [V.Char(c) for c in value.data]
    if k == "dictionary":
        return [V.Block([V.String(key), val]) for key, val in value.data.items()]
    if k == "object":
        return [V.Block([V.String(key), val]) for key, val in value.data.items()]
    if k == "range":
        return [V.Integer(i) for i in range_values(value)]
    if k == "binary":
        return [V.Integer(b) for b in value.data]
    return [value]


@impl("keys")
def _keys(ev, args):
    value = args[0]
    if value.kind in ("dictionary", "object"):
        return V.Block([V.String(k) for k in value.data.keys()])
    fail("cannot get keys of non-dictionary", "Type Error")


@impl("values")
def _values(ev, args):
    value = args[0]
    if value.kind in ("dictionary", "object"):
        return V.Block(list(value.data.values()))
    fail("cannot get values of non-dictionary", "Type Error")


@impl("hasKey?")
def _has_key(ev, args):
    d, key = args
    name = key.data if isinstance(key, (V.Literal, V.Word, V.String)) else V.to_string(key)
    if d.kind in ("dictionary", "object"):
        return V.Logical(name in d.data)
    return V.Logical(False)


@impl("key?")
def _key_q(ev, args):
    return _has_key(ev, args)


# ---------------------------------------------------------------------------
# get / set
# ---------------------------------------------------------------------------
@impl("get")
def _get(ev, args):
    return get_value(ev, args[0], args[1])


@impl("set")
def _set(ev, args):
    container, key, value = args
    if isinstance(container, (V.Literal, V.PathLiteral)):
        getter, setter = ev.inplace_target(container)
        container = getter()
        set_value(ev, container, key, value)
        setter(container)
        return value
    set_value(ev, container, key, value)
    return value


# ---------------------------------------------------------------------------
# searching
# ---------------------------------------------------------------------------
def _member_set(collection: V.Block):
    """Cached set of members for big blocks (membership tests are hot)."""
    if len(collection.data) < 64:
        return None
    cache = getattr(collection, "_member_cache", None)
    if cache is not None and cache[0] == len(collection.data):
        return cache[1]
    try:
        members = {V.value_key(x) for x in collection.data}
    except TypeError:  # pragma: no cover - defensive
        members = None
    collection._member_cache = (len(collection.data), members)
    return members


def _block_contains(collection: V.Block, value: V.Value) -> bool:
    members = _member_set(collection)
    if members is not None:
        try:
            return V.value_key(value) in members
        except TypeError:  # pragma: no cover - defensive
            pass
    return any(V.same_value(x, value) for x in collection.data)


@impl("contains?")
def _contains(ev, args):
    collection, value = args
    k = collection.kind
    if k in ("block", "inline"):
        return V.Logical(_block_contains(collection, value))
    if k == "string":
        if isinstance(value, V.Regex):
            return V.Logical(value.compiled.search(collection.data) is not None)
        return V.Logical(V.to_string(value) in collection.data)
    if k in ("dictionary", "object"):
        name = value.data if isinstance(value, (V.Literal, V.Word, V.String)) else V.to_string(value)
        return V.Logical(name in collection.data)
    if k == "range":
        return V.Logical(V.same_value(collection, value) or
                         any(V.same_value(V.Integer(i), value) for i in range_values(collection)))
    if k == "null":
        return V.Logical(False)
    if k == "binary":
        if value.kind == "binary":
            return V.Logical(value.data in collection.data)
        return V.Logical(bytes([to_int(value)]) in collection.data)
    return V.Logical(False)


@impl("in?")
def _in(ev, args):
    return _contains(ev, [args[1], args[0]])


@impl("index")
def _index(ev, args):
    collection, value = args
    if collection.kind == "string":
        needle = V.to_string(value)
        found = collection.data.find(needle)
        return V.Integer(found) if found >= 0 else V.NULL
    items = _items_of(ev, collection)
    if isinstance(items, list) and len(items) >= 64:
        try:
            needle = V.value_key(value)
            rebuild = getattr(collection, "_index_cache", None)
            if rebuild is None or rebuild[0] != len(items):
                table = {}
                for i, item in enumerate(items):
                    table.setdefault(V.value_key(item), i)
                rebuild = (len(items), table)
                collection._index_cache = rebuild
            found = rebuild[1].get(needle)
            return V.Integer(found) if found is not None else V.NULL
        except TypeError:  # pragma: no cover - defensive
            pass
    for i, item in enumerate(items):
        if V.same_value(item, value):
            return V.Integer(i)
    return V.NULL


@impl("empty?")
def _empty_q(ev, args):
    value = args[0]
    if value.kind in ("null", "nothing", "void"):
        return V.Logical(True)
    return V.Logical(collection_size(value) == 0)


@impl("empty")
def _empty(ev, args):
    value = args[0]
    setter = None
    value, setter = inplace(ev, value)
    if value.kind in ("block", "inline"):
        value.data.clear()
        result = value
    elif value.kind == "dictionary":
        value.data.clear()
        result = value
    elif value.kind == "string":
        result = V.String("")
    else:
        fail("cannot empty value", "Type Error")
    if setter:
        setter(result)
    return result


# ---------------------------------------------------------------------------
# slicing / reversing / sorting
# ---------------------------------------------------------------------------
@impl("slice")
def _slice(ev, args):
    collection, offset, length = args
    items = _items_of(ev, collection)
    start = to_int(offset)
    if length is None:
        end = len(items)
    else:
        end = to_int(length) + 1
    if start < 0:
        start += len(items)
    result = items[start:end]
    if collection.kind == "string":
        return V.String("".join(V.to_string(x) for x in result))
    return V.Block(result)


@impl("reverse")
def _reverse(ev, args):
    value = args[0]
    setter = None
    value, setter = inplace(ev, value)
    if value.kind in ("block", "inline"):
        value.data.reverse()
        result = value
    elif value.kind == "string":
        result = V.String(value.data[::-1])
    elif value.kind == "dictionary":
        result = V.Dictionary(dict(reversed(list(value.data.items()))))
    else:
        result = value
    if setter:
        setter(result)
    return result


def sort_key(parts):
    def key(value):
        return _sort_key_value(value, parts)

    return key


def _sort_key_value(value: V.Value, parts=None):
    if parts:
        for part in parts:
            value = get_value(None, value, part)
    if is_num(value):
        return (0, to_number(value))
    if value.kind == "string":
        return (1, value.data)
    if value.kind == "char":
        return (1, value.data)
    if value.kind == "logical":
        return (2, 1 if value.data else 0)
    return (3, V.to_string(value))


@impl("sort")
def _sort(ev, args):
    collection = args[0]
    setter = None
    collection, setter = inplace(ev, collection)

    descending = attr_true(ev, "descending")
    # ``sort`` is case-insensitive unless ``.sensitive`` is given
    sensitive = attr_true(ev, "sensitive")
    by = attr(ev, "by", None)
    by_values = attr_true(ev, "values")

    key_parts = None
    if by is not None:
        if isinstance(by, V.Literal):
            key_parts = [by]
        elif isinstance(by, V.Block):
            key_parts = list(by.data)

    def keyfunc(item):
        target = item
        if key_parts:
            for part in key_parts:
                target = get_value(ev, target, part)
            return _sort_key_value(target)
        if is_num(item):
            return (0, to_number(item))
        if item.kind in ("string", "char"):
            text = item.data
            return (1, text if sensitive else text.lower())
        if item.kind == "logical":
            return (2, 1 if item.data is True else (0 if item.data is False else -1))
        if item.kind in ("block", "inline"):
            return (3, tuple(_sort_key_value(x) for x in item.data))
        return (4, V.to_string(item))

    if collection.kind in ("block", "inline"):
        collection.data.sort(key=keyfunc, reverse=descending)
        result = collection
    elif collection.kind == "dictionary":
        if by_values:
            items = sorted(collection.data.items(), key=lambda kv: keyfunc(kv[1]), reverse=descending)
        else:
            items = sorted(collection.data.items(), key=lambda kv: keyfunc(V.String(kv[0])), reverse=descending)
        result = V.Dictionary(dict(items))
    else:
        fail("cannot sort value", "Type Error")

    if setter:
        setter(result)
    return result


@impl("sorted?")
def _sorted_q(ev, args):
    items = _items_of(ev, args[0])
    for a, b in zip(items, items[1:]):
        if compare(a, b) > 0:
            return V.Logical(False)
    return V.Logical(True)


@impl("shuffle")
def _shuffle(ev, args):
    value = args[0]
    setter = None
    value, setter = inplace(ev, value)
    if value.kind in ("block", "inline"):
        _random.shuffle(value.data)
        result = value
    elif value.kind == "string":
        chars = list(value.data)
        _random.shuffle(chars)
        result = V.String("".join(chars))
    else:
        fail("cannot shuffle value", "Type Error")
    if setter:
        setter(result)
    return result


@impl("unique")
def _unique(ev, args):
    value = args[0]
    setter = None
    value, setter = inplace(ev, value)
    if value.kind not in ("block", "inline"):
        fail("cannot get unique items of non-block", "Type Error")
    out: List[V.Value] = []
    for item in value.data:
        if not any(V.same_value(item, x) for x in out):
            out.append(item)
    value.data[:] = out
    result = value
    if setter:
        setter(result)
    return result


@impl("distinct")
def _distinct(ev, args):
    return _unique(ev, args)


@impl("flatten")
def _flatten(ev, args):
    """Flatten nested blocks (deep by default, ``.once`` for one level)."""
    value = args[0]
    depth = attr(ev, "depth", None)
    limit = to_int(depth) if depth is not None else -1
    if attr_true(ev, "once"):
        limit = 1
    out: List[V.Value] = []

    def walk(items, level):
        for item in items:
            if item.kind in ("block", "inline") and (limit < 0 or level < limit):
                walk(item.data, level + 1)
            elif not (item.kind in ("block", "inline") and not item.data):
                out.append(item)

    walk(_items_of(ev, value), 0)
    return V.Block(out)


@impl("repeat")
def _repeat(ev, args):
    value, count = args[0], args[1]
    n = to_int(count)
    if value.kind == "string":
        return V.String(value.data * n)
    if value.kind in ("block", "inline"):
        return V.Block(value.data * n)
    if value.kind == "char":
        return V.String(value.data * n)
    return V.Block([value] * n)


@impl("range")
def _range(ev, args):
    a, b = args[0], args[1]
    step = attr(ev, "step", None)
    n = to_int(step) if step is not None else 1
    if isinstance(a, V.Range):
        return V.Range(a.start, a.stop, n)
    return V.Range(to_int(a), to_int(b), n)


@impl("array")
def _array(ev, args):
    from .core import _array as arr

    return arr(ev, args)


# ---------------------------------------------------------------------------
# set operations
# ---------------------------------------------------------------------------
def _set_of(value: V.Value) -> List[V.Value]:
    items = value.data if isinstance(value, V.Block) else list(seq_of(value))
    out: List[V.Value] = []
    for item in items:
        if not any(V.same_value(item, x) for x in out):
            out.append(item)
    return out


@impl("union")
def _union(ev, args):
    a, b = _set_of(args[0]), _set_of(args[1])
    out = list(a)
    for item in b:
        if not any(V.same_value(item, x) for x in out):
            out.append(item)
    return V.Block(out)


@impl("intersection")
def _intersection(ev, args):
    a, b = _set_of(args[0]), _set_of(args[1])
    return V.Block([x for x in a if any(V.same_value(x, y) for y in b)])


@impl("difference")
def _difference(ev, args):
    a, b = _set_of(args[0]), _set_of(args[1])
    symmetric = attr_true(ev, "symmetric")
    left = [x for x in a if not any(V.same_value(x, y) for y in b)]
    if not symmetric:
        return V.Block(left)
    right = [y for y in b if not any(V.same_value(y, x) for x in a)]
    return V.Block(left + right)


@impl("powerset")
def _powerset(ev, args):
    items = _set_of(args[0])
    result: List[V.Value] = []
    n = len(items)
    for mask in range(1 << n):
        result.append(V.Block([items[i] for i in range(n) if mask & (1 << i)]))
    return V.Block(result)


@impl("subset?")
def _subset(ev, args):
    a, b = _set_of(args[0]), _set_of(args[1])
    inside = all(any(V.same_value(x, y) for y in b) for x in a)
    if inside and attr_true(ev, "proper"):
        return V.Logical(len(a) < len(b))
    return V.Logical(inside)


@impl("superset?")
def _superset(ev, args):
    result = _subset(ev, [args[1], args[0]])
    if attr_true(ev, "proper"):
        return V.Logical(V.is_true(result) and
                         len(_set_of(args[0])) > len(_set_of(args[1])))
    return result


@impl("disjoint?")
def _disjoint(ev, args):
    a, b = _set_of(args[0]), _set_of(args[1])
    return V.Logical(not any(any(V.same_value(x, y) for y in b) for x in a))


# ---------------------------------------------------------------------------
# zip / unzip / tally / total / rotate / clip
# ---------------------------------------------------------------------------
@impl("zip")
def _zip(ev, args):
    a = args[0].data if args[0].kind in ("block", "inline") else list(seq_of(args[0]))
    b = args[1].data if args[1].kind in ("block", "inline") else list(seq_of(args[1]))
    out = []
    for i in range(max(len(a), len(b))):
        left = a[i] if i < len(a) else V.NULL
        right = b[i] if i < len(b) else V.NULL
        out.append(V.Block([left, right]))
    return V.Block(out)


@impl("unzip")
def _unzip(ev, args):
    a = args[0].data if args[0].kind in ("block", "inline") else list(seq_of(args[0]))
    b = args[1].data if args[1].kind in ("block", "inline") else list(seq_of(args[1]))
    left = [x.data[0] if isinstance(x, V.Block) and x.data else V.NULL for x in a]
    right = [x.data[1] if isinstance(x, V.Block) and len(x.data) > 1 else V.NULL for x in b]
    return V.Block(left + right)


@impl("tally")
def _tally(ev, args):
    items = _items_of(ev, args[0])
    result = V.Dictionary({})
    for item in items:
        key = V.to_string(item)
        if key in result.data:
            result.data[key] = V.Integer(to_int(result.data[key]) + 1)
        else:
            result.data[key] = V.Integer(1)
    return result


@impl("total")
def _total(ev, args):
    return V.Integer(len(_items_of(ev, args[0])))


@impl("rotate")
def _rotate(ev, args):
    collection, amount = args[0], args[1]
    items = _items_of(ev, collection)
    if not items:
        return collection
    n = to_int(amount) % len(items)
    if attr_true(ev, "left"):
        rotated = items[n:] + items[:n]
    else:
        rotated = items[-n:] + items[:-n] if n else items[:]
    if collection.kind == "string":
        return V.String("".join(V.to_string(x) for x in rotated))
    return V.Block(rotated)


@impl("clip")
def _clip(ev, args):
    collection, minimum, maximum = args
    out = []
    for item in _items_of(ev, collection):
        value = to_number(item)
        if value < to_number(minimum):
            item = minimum
        elif value > to_number(maximum):
            item = maximum
        out.append(item)
    return V.Block(out)


@impl("sample")
def _sample(ev, args):
    items = _items_of(ev, args[0])
    if not items:
        return V.NULL
    return _random.choice(items)


@impl("permutate")
def _permutate(ev, args):
    from itertools import permutations, combinations

    items = _items_of(ev, args[0])
    size = attr(ev, "size", None)
    kind = attr(ev, "exact", None)
    n = len(items) if size is None else to_int(size)
    if attr_true(ev, "combinations") or kind is not None:
        combos = combinations(items, n)
    else:
        combos = permutations(items, n)
    return V.Block([V.Block(list(c)) for c in combos])


def _take_text(collection, chunk):
    if collection.kind == "string":
        return V.String("".join(V.to_string(x) for x in chunk))
    if collection.kind in ("block", "inline"):
        return V.Block(list(chunk))
    return V.Block(list(chunk))


@builtin("take", arity=2, attrs=["last", "times"])
def _take(ev, args):
    collection = args[0]
    value, setter = inplace(ev, collection)
    times = attr(ev, "times", None)
    n = to_int(args[1]) if len(args) > 1 else (to_int(times) if times is not None else 1)
    last = attr_true(ev, "last")
    items = _items_of(ev, value)
    chunk = items[-n:] if last else items[:n]
    result = _take_text(value, chunk)
    if setter:
        setter(result)
    return result


@builtin("drop", arity=1, attrs=["last", "times"])
def _drop(ev, args):
    collection = args[0]
    value, setter = inplace(ev, collection)
    times = attr(ev, "times", None)
    n = to_int(times) if times is not None else 1
    last = attr_true(ev, "last")
    items = _items_of(ev, value)
    if n < 0:
        chunk = items[:n] if not last else items[:len(items) + n]
    else:
        chunk = items[:-n] if last else items[n:]
    result = _take_text(value, chunk)
    if setter:
        setter(result)
    return result


@impl("chop")
def _chop(ev, args):
    value = args[0]
    setter = None
    value, setter = inplace(ev, value)
    if value.kind in ("block", "inline") and value.data:
        value.data.pop()
        result = value
    elif value.kind == "string":
        result = V.String(value.data[:-1])
    else:
        result = value
    if setter:
        setter(result)
    return result


@impl("extend")
def _extend(ev, args):
    a, b = args[0], args[1]
    if a.kind in ("dictionary", "object") and b.kind in ("dictionary", "object"):
        a.data.update(b.data)
        return a
    if a.kind in ("block", "inline") and b.kind in ("block", "inline"):
        a.data.extend(b.data)
        return a
    fail("cannot extend value", "Type Error")


@impl("squeeze")
def _squeeze(ev, args):
    """Collapse adjacent duplicate elements."""
    value = args[0]
    if value.kind == "string":
        out = []
        for ch in value.data:
            if not out or out[-1] != ch:
                out.append(ch)
        return V.String("".join(out))
    items = _items_of(ev, value)
    out = []
    for item in items:
        if not out or not V.same_value(out[-1], item):
            out.append(item)
    return V.Block(out)


@builtin("pop", arity=1, attrs=["n"])
def _pop(ev, args):
    value, setter = inplace(ev, args[0])
    n = attr(ev, "n", None)
    count = to_int(n) if n is not None else 1
    if value.kind in ("block", "inline"):
        taken = value.data[-count:]
        del value.data[-count:]
        if setter:
            setter(value)
        if n is None:
            return taken[-1] if taken else V.NULL
        return V.Block(taken)
    if value.kind == "string":
        taken = value.data[-count:]
        value.data = value.data[:-count]
        if setter:
            setter(value)
        if n is None:
            return V.Char(taken[-1]) if taken else V.String("")
        return V.String(taken)
    fail("cannot pop from value", "Type Error")


@builtin("path", arity=1)
def _path(ev, args):
    from pathlib import Path as _Path

    value = args[0]
    text = V.to_string(value)
    p = _Path(text)
    full = p.expanduser().resolve()
    return V.Dictionary({
        "name": V.String(p.name),
        "filename": V.String(p.stem),
        "extension": V.String(p.suffix),
        "directory": V.String(str(p.parent)),
        "absolute": V.String(str(full)),
        "exists": V.Logical(full.exists()),
        "isDirectory": V.Logical(full.is_dir()),
    })


@impl("dump")
def _dump(ev, args):
    return args[0]


@impl("copy")
def _copy(ev, args):
    target, value = args[0], args[1]
    if isinstance(target, (V.Literal, V.PathLiteral)):
        getter, setter = ev.inplace_target(target)
        current = getter()
        if current.kind in ("dictionary", "object") and value.kind in ("dictionary", "object"):
            current.data.update(value.data)
            setter(current)
            return current
        if current.kind in ("block", "inline"):
            current.data.append(value)
            setter(current)
            return current
    return target
