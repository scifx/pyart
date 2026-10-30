"""Arturo-compatible runtime reflection and user-function documentation.

``builtin_docs.json`` is generated from Arturo-Future's library declarations
at the source revision documented in ``tools/build_builtin_metadata.py``. The
runtime can therefore expose the same contracts and examples without depending
on a separate Arturo executable or on network access.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import values as V
from .signatures import SIGNATURES

with (Path(__file__).with_name("builtin_docs.json")).open(encoding="utf-8") as _fh:
    BUILTIN_DOCS = json.load(_fh)


def parse_user_doc_comments(block: V.Block) -> dict[str, Any]:
    """Parse Arturo ``;;`` data comments attached to a function body.

    Supported fields follow Arturo's documented function contract: description,
    options, returns and example. Unknown keys are retained as plain strings so
    custom documentation can be extended without losing information.
    """
    lines = list(getattr(block, "doc_comments", ()))
    result: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        match = re.match(r"([A-Za-z_][A-Za-z_0-9?-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value.startswith("«"):
            result[key] = value[1:].strip()
            continue
        if value.startswith("[") or value.startswith("{"):
            opening, closing = value[0], "]" if value[0] == "[" else "}"
            collected = [value[1:]]
            depth = value.count(opening) - value.count(closing)
            while depth > 0 and i < len(lines):
                part = lines[i]
                i += 1
                collected.append(part)
                depth += part.count(opening) - part.count(closing)
            if collected:
                collected[-1] = collected[-1].rsplit(closing, 1)[0]
            payload = "\n".join(collected).strip()
            if key == "options":
                result[key] = _parse_options(payload)
            elif key == "example":
                result[key] = _split_examples(payload)
            else:
                result[key] = payload
            continue
        if key == "returns":
            result[key] = re.findall(r":([A-Za-z_][A-Za-z_0-9?]*)", value)
        else:
            result[key] = value
    return result


def _parse_options(payload: str) -> list[dict[str, Any]]:
    options = []
    for raw in payload.splitlines():
        line = raw.strip().rstrip(",")
        if not line:
            continue
        match = re.match(r"([A-Za-z_][A-Za-z_0-9?-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        name, spec = match.groups()
        desc = ""
        if "«" in spec:
            spec, desc = spec.split("«", 1)
            desc = desc.strip()
        types = re.findall(r":([A-Za-z_][A-Za-z_0-9?]*)", spec)
        options.append({"name": name, "types": [":" + x for x in types],
                        "description": desc})
    return options


def _split_examples(text: str) -> list[str]:
    result = []
    current = []
    for line in text.splitlines():
        if re.search(r"\.{4,}", line):
            example = "\n".join(current).strip()
            if example:
                result.append(example)
            current = []
        else:
            current.append(line)
    example = "\n".join(current).strip()
    if example:
        result.append(example)
    return result


def _types(values: list[str]) -> V.Block:
    return V.Block([V.Type(name.removeprefix(":")) for name in values])


def _reverse_alias(name: str, requested: str):
    from . import ast as A
    from . import parser as P

    for symbol, target in A.DYNAMIC_INFIX.items():
        if target == name:
            return requested if requested == symbol else symbol, True
    for table, infix in ((P.INFIX_ALIASES, True), (P.PREFIX_ALIASES, False)):
        for symbol, target in table.items():
            if target == name:
                return requested if requested == symbol else symbol, infix
    return None, None


def resolve_info_target(ev, value: V.Value):
    """Resolve literals, strings, aliases and runtime values for ``info``."""
    if isinstance(value, V.PathLiteral):
        parts = value.data
        if not parts:
            name = ""
            target_value = None
        else:
            name = V.to_string(parts[-1])
            first = V.to_string(parts[0])
            target_value = ev.ctx.syms.get(first)
            if target_value is None:
                target_value = ev.ctx.library.lookup(first) or ev.ctx.library.constant(first)
            for part in parts[1:]:
                key = V.to_string(part)
                if isinstance(target_value, (V.Dictionary, V.Object)):
                    member = target_value.data.get(key)
                    if member is None and isinstance(target_value, V.Object) \
                            and isinstance(target_value.proto, V.Type):
                        spec = ev.ctx.library.lookup_type(target_value.proto.data) or {}
                        member = (spec.get("methods") or {}).get(key)
                    target_value = member
                else:
                    target_value = None
                    break
    elif isinstance(value, (V.Literal, V.Word, V.Symbol, V.String)):
        name = value.data
        target_value = None
    elif isinstance(value, V.Function):
        name = value.name
        target_value = value
    else:
        raise ValueError("info expects a symbol, path literal, string, or function")

    from . import ast as A
    from . import parser as P
    canonical = (A.DYNAMIC_INFIX.get(name) or P.INFIX_ALIASES.get(name)
                 or P.PREFIX_ALIASES.get(name) or name)
    if target_value is None:
        target_value = ev.ctx.syms.get(canonical)
        if target_value is None:
            target_value = ev.ctx.library.lookup(canonical)
        if target_value is None:
            target_value = ev.ctx.library.constant(canonical)
    if target_value is None:
        return name, canonical, None
    return name, canonical, target_value


def _signature_args(fn: V.Function, name: str) -> dict[str, list[str]]:
    docs = BUILTIN_DOCS.get(name)
    if docs is not None:
        return {arg["name"]: arg["types"] for arg in docs["args"]}
    if hasattr(fn, "param_types"):
        return {p.data: getattr(fn, "param_types", {}).get(p.data, [":any"])
                for p in fn.params if isinstance(p, (V.Word, V.Literal))}
    signature = SIGNATURES.get(name)
    if signature and signature[0] > 0:
        return {f"arg{i + 1}": [":any"] for i in range(signature[0])}
    return {"": [":nothing"]}


def _attribute_specs(fn: V.Function, name: str) -> list[dict]:
    docs = BUILTIN_DOCS.get(name)
    if docs is not None:
        return docs["attrs"]
    user = getattr(fn, "doc", {}).get("options", [])
    if user:
        return user
    signature = SIGNATURES.get(name)
    if signature:
        return [{"name": attr, "types": [":any"], "description": ""}
                for attr in signature[1]]
    return []


def metadata_for(name: str, requested: str, value: V.Value) -> V.Dictionary:
    """Construct an ``info.get`` dictionary with Arturo's documented fields."""
    info: dict[str, V.Value] = {
        "name": V.String(name),
        "address": V.String(f"0x{id(value):X}"),
        "type": V.Type(value.kind),
    }
    if not isinstance(value, V.Function):
        return V.Dictionary(info)

    docs = BUILTIN_DOCS.get(name, {})
    user = getattr(value, "doc", {})
    description = user.get("description") or docs.get("description")
    module = docs.get("module")
    if description:
        info["description"] = V.String(str(description))
    if module:
        info["module"] = V.String(module)

    arg_map = _signature_args(value, name)
    info["args"] = V.Dictionary({key: _types(types) for key, types in arg_map.items()})
    attrs = _attribute_specs(value, name)
    info["attrs"] = V.Dictionary({
        attr["name"]: V.Dictionary({
            "types": _types(attr.get("types", [])),
            "description": V.String(attr.get("description", "")),
        }) for attr in attrs
    })
    returns = user.get("returns", docs.get("returns", []))
    if not returns:
        returns = [":nothing"]
    info["returns"] = _types(returns)

    examples = user.get("example", docs.get("examples", []))
    if isinstance(examples, str):
        examples = _split_examples(examples)
    info["example"] = V.Block([V.String(example) for example in examples])
    line = docs.get("line")
    source = docs.get("source")
    if line:
        info["line"] = V.Integer(line)
    if source:
        info["source"] = V.String(source)

    alias, infix = _reverse_alias(name, requested)
    if alias:
        info["alias"] = V.String(alias)
        info["infix?"] = V.Logical(bool(infix))
    return V.Dictionary(info)


def _type_text(value: V.Value) -> str:
    if isinstance(value, V.Block):
        return " ".join(V.to_string(item) for item in value.data) or ":nothing"
    return V.to_string(value)


def _line(label: str, text: str) -> str:
    # Arturo's helper right-aligns labels in an eleven-character column.
    return "|    " + label.rjust(11) + "  " + text + "\n"


def _wrapped(text: str, width: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines = []
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = word if not line else line + " " + word
    lines.append(line)
    return lines


def format_info(metadata: V.Dictionary) -> str:
    """Render the same sections/labels as Arturo's `info` help display."""
    data = metadata.data
    name = V.to_string(data["name"])
    kind = V.to_string(data["type"])
    module = V.to_string(data.get("module", V.String("")))
    header_data = kind.ljust(30) + (module.rjust(32) if module else V.to_string(data["address"]).rjust(32))
    out = "|" + "-" * 80 + "\n" + _line(name, header_data)
    if "alias" in data:
        out += _line("alias", V.to_string(data["alias"]))
    out += "|" + "-" * 80 + "\n"
    if "description" in data:
        for line in _wrapped(V.to_string(data["description"])):
            out += _line("", line)
        out += "|" + "-" * 80 + "\n"

    if isinstance(data.get("args"), V.Dictionary):
        args = data["args"].data
        if not args:
            args = {"": V.Block([V.Type("nothing")])}
        first = True
        for arg, types in args.items():
            label = "usage" if first else ""
            text = name + (" " + arg if arg else "") + " " + _type_text(types)
            out += _line(label, text)
            first = False

    attrs = data.get("attrs")
    if isinstance(attrs, V.Dictionary) and attrs.data:
        out += "|\n"
        for index, (attr, spec) in enumerate(attrs.data.items()):
            types = _type_text(spec.data.get("types", V.Block([])))
            desc = V.to_string(spec.data.get("description", V.String("")))
            left = "." + attr + (" " + types if types != ":logical" else "")
            out += _line("options" if index == 0 else "", left + " -> " + desc)

    returns = data.get("returns", V.Block([V.Type("nothing")]))
    if returns.data:
        out += "|\n"
    for index, ret in enumerate(returns.data):
        out += _line("returns" if index == 0 else "", V.to_string(ret))
    out += "|" + "-" * 80 + "\n"
    return out
