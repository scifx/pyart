"""
misc.py - files, paths, dates, crypto, system and module support.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import platform
import socket
import sys
import time
from typing import List

from .. import values as V
from ..evaluator import ArturoError, MISSING
from . import *
from . import (attr, attr_true, fail, impl, num_result, to_int, to_number)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def _path_of(value: V.Value) -> str:
    if value.kind == "string":
        return value.data
    return V.to_string(value)


@builtin("read", arity=1, attrs=["json", "lines", "binary", "file", "csv", "withHeaders",
                                 "delimiter", "xml", "html", "markdown", "toml", "async"])
def _read(ev, args):
    path = _path_of(args[0])
    lines = attr_true(ev, "lines")
    binary = attr_true(ev, "binary")
    as_json = attr_true(ev, "json")
    if binary:
        try:
            with open(path, "rb") as fh:
                return V.Binary(fh.read())
        except OSError as exc:
            raise ArturoError("File Error", str(exc))
    # `read` also accepts plain data: when the argument is not a real path the
    # string itself is the source (Arturo's getSource)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except FileNotFoundError:
        if attr_true(ev, "file"):
            raise ArturoError("File Error", f"File not found: {path}")
        text = path
    except IsADirectoryError:
        raise ArturoError("File Error", f"Is a directory: {path}")
    except OSError:
        text = path
    if lines:
        return V.Block([V.String(x) for x in text.splitlines()])
    if as_json:
        return json_to_value(text)
    if attr_true(ev, "csv"):
        return _parse_csv_text(ev, text)
    return V.String(text)


def _parse_csv_text(ev, text: str):
    delimiter = ","
    d = attr(ev, "delimiter", None)
    if d is not None:
        delimiter = V.to_string(d)
    rows = [line.split(delimiter) for line in text.splitlines() if line != ""]
    with_headers = attr_true(ev, "withHeaders")
    if not with_headers:
        return V.Block([V.Block([V.String(c) for c in row]) for row in rows])
    if not rows:
        return V.Block([])
    headers = rows[0]
    out = []
    for row in rows[1:]:
        d = {}
        for i, h in enumerate(headers):
            d[h] = V.String(row[i]) if i < len(row) else V.String("")
        out.append(V.Dictionary(d))
    return V.Block(out)


@builtin("write", arity=2, attrs=["json", "directory", "append"])
def _write(ev, args):
    path = _path_of(args[0])
    value = args[1]
    if attr_true(ev, "json"):
        text = value_to_json(value)
    else:
        text = V.to_string(value) if value.kind != "block" else "\n".join(
            V.to_string(x) for x in value.data)
    mode = "a" if attr_true(ev, "append") else "w"
    try:
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        raise ArturoError("File Error", str(exc))
    return V.NULL


@impl("pause")
def _pause(ev, args):
    """Pause for Arturo's integer-millisecond or time-quantity duration."""
    value = args[0]
    if isinstance(value, V.Integer):
        milliseconds = value.data
    elif isinstance(value, V.Quantity):
        unit = value.unit.strip().lower()
        # Arturo quantities are dimensioned; accept time units only and convert
        # the stored magnitude to the millisecond base used by `pause`.
        factors = {
            "ns": 1e-6, "nanosecond": 1e-6, "nanoseconds": 1e-6,
            "us": 1e-3, "µs": 1e-3, "μs": 1e-3,
            "ms": 1.0, "millisecond": 1.0, "milliseconds": 1.0,
            "s": 1000.0, "sec": 1000.0, "second": 1000.0, "seconds": 1000.0,
            "min": 60_000.0, "minute": 60_000.0, "minutes": 60_000.0,
            "h": 3_600_000.0, "hr": 3_600_000.0, "hrs": 3_600_000.0,
            "hour": 3_600_000.0, "hours": 3_600_000.0,
            "day": 86_400_000.0, "days": 86_400_000.0,
            "wk": 604_800_000.0, "week": 604_800_000.0, "weeks": 604_800_000.0,
            "mo": 2_629_746_000.0, "month": 2_629_746_000.0,
            "months": 2_629_746_000.0,
            "yr": 31_556_952_000.0, "year": 31_556_952_000.0,
            "years": 31_556_952_000.0,
        }
        if unit not in factors:
            fail(f"cannot use {unit!r} as a time duration", "Type Error")
        milliseconds = to_number(value.value) * factors[unit]
    else:
        fail("pause expects an integer or time quantity", "Type Error")
    time.sleep(max(0.0, float(milliseconds)) / 1000.0)
    return V.VOID


@builtin("exists?", arity=1)
def _exists(ev, args):
    return V.Logical(os.path.exists(_path_of(args[0])))


@builtin("file?", arity=1)
def _file_q(ev, args):
    return V.Logical(os.path.isfile(_path_of(args[0])))


@builtin("directory?", arity=1)
def _directory_q(ev, args):
    return V.Logical(os.path.isdir(_path_of(args[0])))


@builtin("list", arity=1, attrs=["recursive"])
def _list(ev, args):
    path = _path_of(args[0])
    out = []
    try:
        for name in sorted(os.listdir(path)):
            full = name if path in ("", ".") else os.path.join(path, name)
            out.append(V.String(full))
    except OSError as exc:
        raise ArturoError("File Error", str(exc))
    return V.Block(out)


@builtin("delete", arity=1)
def _delete(ev, args):
    path = _path_of(args[0])
    try:
        if os.path.isdir(path):
            import shutil

            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as exc:
        raise ArturoError("File Error", str(exc))
    return V.NULL


@builtin("copy", arity=2)
def _copy_file(ev, args):
    import shutil

    try:
        shutil.copy(_path_of(args[0]), _path_of(args[1]))
    except OSError as exc:
        raise ArturoError("File Error", str(exc))
    return V.NULL


@builtin("move", arity=2)
def _move_file(ev, args):
    import shutil

    try:
        shutil.move(_path_of(args[0]), _path_of(args[1]))
    except OSError as exc:
        raise ArturoError("File Error", str(exc))
    return V.NULL


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
@impl("extract")
def _extract(ev, args):
    path = _path_of(args[0])
    for key in ("extension", "filename", "basename", "directory"):
        if attr_present(ev, key) is not MISSING:
            return _extract_part(path, key)
    return V.Dictionary({
        "directory": V.String(os.path.dirname(path)),
        "basename": V.String(os.path.basename(path)),
        "filename": V.String(os.path.splitext(os.path.basename(path))[0]),
        "extension": V.String(os.path.splitext(path)[1]),
    })


def _extract_part(path: str, key: str) -> V.Value:
    if key == "filename":
        return V.String(os.path.splitext(os.path.basename(path))[0])
    if key in ("file", "basename"):
        return V.String(os.path.basename(path))
    if key == "directory":
        return V.String(os.path.dirname(path) or ".")
    if key == "extension":
        return V.String(os.path.splitext(path)[1])
    if key == "filename-with-extension":
        return V.String(os.path.basename(path))
    if key == "name":
        return V.String(os.path.splitext(os.path.basename(path))[0])
    return V.String(path)


@builtin("relative", arity=1)
def _relative(ev, args):
    path = _path_of(args[0])
    if os.path.isabs(path):
        return V.String(path)
    base = os.path.dirname(os.path.abspath(ev.ctx.path[-1])) if ev.ctx.path else os.getcwd()
    return V.String(os.path.join(base, path))


@builtin("module", arity=0)
def _module(ev, args):
    return V.String(ev.ctx.path[-1] if ev.ctx.path else "")


@builtin("script", arity=0)
def _script(ev, args):
    return V.String(ev.ctx.path[0] if ev.ctx.path else "")


@builtin("arg", arity=0)
def _arg(ev, args):
    """Return the raw command-line arguments as a block of strings."""
    return V.Block([V.String(str(a)) for a in getattr(ev.ctx, "argv", [])])


@builtin("args", arity=0)
def _args(ev, args):
    """Parse positional values and command-line switches into a dictionary."""
    argv = [str(item) for item in getattr(ev.ctx, "argv", [])]
    result = {}
    positional = []
    i = 0
    while i < len(argv):
        item = argv[i]
        if item.startswith("-") and item != "-" and not item[1:2].isdigit():
            option = item.lstrip("-")
            if ":" in option:
                key, raw = option.split(":", 1)
                result[key] = _parse_arg_value(raw)
            else:
                key = option
                if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    i += 1
                    result[key] = _parse_arg_value(argv[i])
                else:
                    result[key] = V.TRUE
        else:
            positional.append(_parse_arg_value(item))
        i += 1
    if positional:
        result["values"] = V.Block(positional)
    elif any(key not in ("values",) for key in result):
        result["values"] = V.Block([])
    return V.Dictionary(result)


def _parse_arg_value(text: str) -> V.Value:
    try:
        return V.Integer(int(text))
    except ValueError:
        try:
            return V.Floating(float(text))
        except ValueError:
            return V.String(text)


@builtin("sys", arity=0)
def _sys(ev, args):
    """Return Python-host system information using Arturo's field names."""
    system = platform.system().lower()
    os_name = {"darwin": "macos", "windows": "windows"}.get(system, system)
    built = V.Date(datetime.datetime.now().astimezone())
    return V.Dictionary({
        "author": V.String("Pyart contributors"),
        "copyright": V.String("(c) 2026 Pyart contributors"),
        "version": V.Version("0.10.1-dev+pyart"),
        "codename": V.String("Pyart"),
        "built": built,
        "deps": V.Dictionary({}),
        "binary": V.String(sys.executable),
        "cpu": V.Dictionary({
            "arch": V.Literal(platform.machine() or "unknown"),
            "endian": V.Literal(sys.byteorder),
            "cores": V.Integer(os.cpu_count() or 1),
        }),
        "os": V.Literal(os_name),
        "hostname": V.String(socket.gethostname()),
        "release": V.Literal("python"),
    })


@builtin("standalone?", arity=0)
def _standalone(ev, args):
    return V.Logical(getattr(ev.ctx, "standalone", True))


@builtin("exit", arity=0)
def _exit(ev, args):
    raise SystemExit(0)


@builtin("system", arity=0)
def _system(ev, args):
    return V.Dictionary({"os": V.String(sys.platform), "arch": V.String("amd64")})


# ---------------------------------------------------------------------------
# Crypto / hashing
# ---------------------------------------------------------------------------
@builtin("absolute", arity=1)
def _absolute_path(ev, args):
    import os

    text = V.to_string(args[0])
    if os.path.isabs(text):
        return V.String(os.path.normpath(text))
    base = os.path.dirname(os.path.abspath(ev.ctx.path[-1])) if ev.ctx.path else os.getcwd()
    return V.String(os.path.normpath(os.path.join(base, text)))


@builtin("absolute?", arity=1)
def _absolute_q(ev, args):
    import os

    return V.Logical(os.path.isabs(V.to_string(args[0])))


@builtin("digest", arity=1, attrs=["sha", "sha1", "sha256", "sha512", "md5"])
def _digest(ev, args):
    value = args[0]
    text = value.data if value.kind == "string" else V.to_string(value)
    algorithm = "md5"
    if attr_true(ev, "sha") or attr_true(ev, "sha1"):
        algorithm = "sha1"
    for name in ("md5", "sha256", "sha512"):
        if attr_true(ev, name):
            algorithm = name
            break
    return V.String(hashlib.new(algorithm, text.encode()).hexdigest())


@builtin("crc", arity=1)
def _crc(ev, args):
    import binascii

    value = args[0]
    text = value.data if value.kind == "string" else V.to_string(value)
    return V.String(f"{binascii.crc32(text.encode()) & 0xFFFFFFFF:08X}")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
@builtin("now", arity=0)
def _now(ev, args):
    return V.Date(datetime.datetime.now().astimezone())


@builtin("today", arity=0)
def _today(ev, args):
    return V.Date(datetime.datetime.now().astimezone())


@builtin("timestamp", arity=1)
def _timestamp(ev, args):
    value = args[0]
    if value.kind == "date":
        return V.Integer(int(value.data.timestamp()))
    return V.Integer(to_int(value))


@builtin("leap?", arity=1)
def _leap(ev, args):
    value = args[0]
    year = value.data.year if value.kind == "date" else to_int(value)
    return V.Logical((year % 4 == 0 and year % 100 != 0) or year % 400 == 0)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def json_to_value(text: str) -> V.Value:
    import json

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArturoError("JSON Error", str(exc))
    return _from_python(data)


def _from_python(data) -> V.Value:
    if data is None:
        return V.NULL
    if isinstance(data, bool):
        return V.Logical(data)
    if isinstance(data, int):
        return V.Integer(data)
    if isinstance(data, float):
        return V.Floating(data)
    if isinstance(data, str):
        return V.String(data)
    if isinstance(data, list):
        return V.Block([_from_python(x) for x in data])
    if isinstance(data, dict):
        return V.Dictionary({k: _from_python(v) for k, v in data.items()})
    return V.String(str(data))


def value_to_json(value: V.Value, indent=None) -> str:
    import json

    return json.dumps(_to_python(value), indent=indent, ensure_ascii=False)


def _to_python(value: V.Value):
    k = value.kind
    if k == "null" or k == "void":
        return None
    if k == "logical":
        return value.data is True
    if k == "integer":
        return value.data
    if k == "floating":
        return value.data
    if k in ("string", "char", "word", "literal", "version"):
        return value.data
    if k in ("block", "inline"):
        return [_to_python(x) for x in value.data]
    if k in ("dictionary", "object"):
        return {key: _to_python(val) for key, val in value.data.items()}
    return V.to_string(value)


@builtin("parse.json", arity=1)
def _parse_json(ev, args):
    return json_to_value(V.to_string(args[0]))


@builtin("write.json", arity=2)
def _write_json(ev, args):
    value, path = args[0], args[1]
    text = value_to_json(value)
    if path.kind == "null":
        return V.String(text)
    with open(_path_of(path), "w", encoding="utf-8") as fh:
        fh.write(text)
    return V.NULL


@builtin("read.json", arity=1)
def _read_json(ev, args):
    text = V.to_string(args[0])
    if os.path.exists(text):
        with open(text, encoding="utf-8") as fh:
            text = fh.read()
    return json_to_value(text)


# ---------------------------------------------------------------------------
# Modules / imports
# ---------------------------------------------------------------------------
@builtin("import", arity=1, attrs=["lean", "version", "noparse", "gui", "noalias", "global"])
def _import(ev, args):
    target = args[0]
    name = V.to_string(target)
    candidates = [name, name + ".art"]
    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as fh:
                source = fh.read()
            from ..parser import parse
            from ..ast import build

            block = parse(source)
            tree = build(block, ev.ctx.library)
            ev.ctx.path.append(candidate)
            try:
                result = ev.eval_node(tree)
            finally:
                ev.ctx.path.pop()
            return result if result is not V.VOID else V.NULL
    raise ArturoError("Import Error", f"cannot import: {name}")


@builtin("export", arity=1)
def _export(ev, args):
    return V.NULL
