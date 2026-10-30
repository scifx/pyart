#!/usr/bin/env python3
"""Extract Arturo builtin documentation from an Arturo-Future source checkout.

Use the source revision pinned by the language skill (933420d):

    python3 tools/build_builtin_metadata.py /path/to/Arturo-Future/src/library

The generated snapshot is checked in, so the Python runtime itself does not
need the upstream source or network access.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import textwrap
from pathlib import Path

SOURCE_REVISION = "933420d"
DECL = re.compile(r'(?m)^\s*builtin\s+"([^"]+)"\s*,')
TYPE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\??")


def balanced(text: str, start: int, opener="{", closer="}") -> tuple[str, int]:
    """Return balanced text (without delimiters) and the next input offset."""
    depth = 0
    quote = None
    triple = False
    escaped = False
    i = start
    while i < len(text):
        if quote == '"' and text.startswith('"""', i):
            if triple:
                triple = False
                quote = None
                i += 3
                continue
            triple = True
            quote = '"'
            i += 3
            continue
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif not triple and ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return "", len(text)


def field_block(chunk: str, key: str) -> str:
    match = re.search(r"\b" + re.escape(key) + r"\s*=\s*\{", chunk)
    if not match:
        return ""
    return balanced(chunk, match.end() - 1)[0]


def types_of(text: str) -> list[str]:
    # Do not mistake tuple field names/descriptions for types: callers pass only
    # the type-set expression (the contents of `{...}`).
    return [":" + name.lower() for name in TYPE.findall(text)]


def parse_args(chunk: str) -> list[dict]:
    block = field_block(chunk, "args")
    if not block:
        return []
    args = []
    for match in re.finditer(r'"([^"\n]+)"\s*:\s*\{([^{}]*)\}', block):
        args.append({"name": match.group(1), "types": types_of(match.group(2))})
    return args


def parse_attrs(chunk: str) -> list[dict]:
    block = field_block(chunk, "attrs")
    if not block:
        return []
    attrs = []
    pattern = re.compile(
        r'"([^"\n]+)"\s*:\s*\(\s*\{([^{}]*)\}\s*,\s*"((?:\\.|[^"\\])*)"\s*\)'
    )
    for match in pattern.finditer(block):
        desc = _decode_string(match.group(3))
        attrs.append({"name": match.group(1), "types": types_of(match.group(2)),
                      "description": desc})
    return attrs


def parse_returns(chunk: str) -> list[str]:
    match = re.search(r"\breturns\s*=\s*\{([^{}]*)\}", chunk)
    return types_of(match.group(1)) if match else []


def parse_example(chunk: str) -> list[str]:
    match = re.search(r'\bexample\s*=\s*"""(.*?)"""\s*:', chunk, re.S)
    if not match:
        return []
    raw = textwrap.dedent(match.group(1)).strip()
    # The upstream separator represents distinct, independently runnable
    # examples. It is not part of the code passed to `do`.
    examples = []
    for part in re.split(r"(?m)^\s*\.{10,}\s*$", raw):
        code = textwrap.dedent(part).strip()
        if code.startswith("copy\n"):
            code = code[5:].lstrip()
        if code:
            examples.append(code)
    return examples


def _decode_string(value: str) -> str:
    try:
        return ast.literal_eval('"' + value + '"')
    except (SyntaxError, ValueError):
        return value


def parse_module(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    matches = list(DECL.finditer(source))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        chunk = source[match.end():end]
        description = re.search(r'\bdescription\s*=\s*"((?:\\.|[^"\\])*)"', chunk)
        desc = ""
        if description:
            desc = _decode_string(description.group(1))
        line = source.count("\n", 0, match.start()) + 1
        result[match.group(1)] = {
            "description": desc,
            "module": path.stem,
            "args": parse_args(chunk),
            "attrs": parse_attrs(chunk),
            "returns": parse_returns(chunk),
            "examples": parse_example(chunk),
            "line": line,
            "source": ("https://github.com/scifx/Arturo-Future/blob/"
                       f"{SOURCE_REVISION}/src/library/{path.name}#L{line}"),
            "source_revision": SOURCE_REVISION,
        }
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    source_dir = Path(sys.argv[1])
    metadata = {}
    for path in sorted(source_dir.glob("*.nim")):
        metadata.update(parse_module(path))
    out = Path(__file__).resolve().parents[1] / "arturo" / "builtin_docs.json"
    out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {len(metadata)} builtin records to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
