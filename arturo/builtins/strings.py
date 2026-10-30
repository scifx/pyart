"""
strings.py - string functions, including ``~"..."`` template rendering.
"""
from __future__ import annotations

import re as _re
import unicodedata
from typing import List

from .. import values as V
from ..evaluator import ArturoError, MISSING
from . import *
from . import (VOID, attr, attr_true, fail, impl, is_num, num_result, seq_of,
               to_int, to_number)


def _str(value: V.Value) -> str:
    return V.to_string(value)


@impl("upper")
def _upper(ev, args):
    value = args[0]
    if value.kind == "char":
        return V.Char(value.data.upper())
    return V.String(_str(value).upper())


@impl("lower")
def _lower(ev, args):
    value = args[0]
    if value.kind == "char":
        return V.Char(value.data.lower())
    return V.String(_str(value).lower())


@impl("capitalize")
def _capitalize(ev, args):
    value = args[0]
    text = _str(value)
    # ``capitalize`` upper-cases the first letter of every word and leaves the
    # rest of the text untouched (unless ``.preserve`` is not given... it is
    # always untouched in Arturo)
    return V.String(text[:1].upper() + text[1:])


@impl("strip")
def _strip(ev, args):
    text = _str(args[0])
    which = []
    if attr_true(ev, "start"):
        which.append("leading")
    if attr_true(ev, "end"):
        which.append("trailing")
    if attr_true(ev, "leading"):
        which.append("leading")
    if attr_true(ev, "trailing"):
        which.append("trailing")
    if not which:
        return V.String(text.strip())
    if "leading" in which and "trailing" in which:
        return V.String(text.strip())
    if "leading" in which:
        return V.String(text.lstrip())
    return V.String(text.rstrip())


@builtin("pad", arity=2, attrs=["center", "right"])
def _pad(ev, args):
    text, width = args[0], args[1]
    s = _str(text)
    n = to_int(width)
    # every attribute has to be popped, even when we return early: attributes
    # left on the stack would leak into the next call
    fill = attr(ev, "with", None)
    center = attr_true(ev, "center")
    right = attr_true(ev, "right")
    ch = _str(fill) if fill is not None else " "
    if len(s) >= n:
        return V.String(s)
    if center:
        total = n - len(s)
        left = total // 2
        return V.String(ch * left + s + ch * (total - left))
    if right:
        return V.String(s + ch * (n - len(s)))
    return V.String(ch * (n - len(s)) + s)


@impl("truncate")
def _truncate(ev, args):
    text = _str(args[0])
    n = to_int(args[1])
    with_dots = attr_true(ev, "with")
    if n >= len(text):
        return V.String(text)
    if with_dots:
        return V.String(text[: max(0, n - 3)] + "...")
    return V.String(text[:n])


@impl("replace")
def _replace(ev, args):
    text, what, replacement = args
    setter = None
    if isinstance(text, (V.Literal, V.PathLiteral)):
        getter, setter = ev.inplace_target(text)
        text = getter()
        if text.kind == "string" and getattr(text, "frozen", False):
            text = V.String(text.data)
    elif text.kind == "string":
        # a plain expression argument is never mutated in place
        text = V.String(text.data)

    if isinstance(what, V.Regex):
        count = 0
        if attr_true(ev, "once") or attr_true(ev, "first") or attr_true(ev, "firstOnly"):
            count = 1
        repl = _re.sub(r"\$(\d+)", lambda m: "\\" + m.group(1), _str(replacement))
        result = V.String(what.compiled.sub(repl, text.data, count=count))
    elif isinstance(text, V.Block):
        result = V.Block([replacement if V.same_value(item, what) else item
                          for item in text.data])
    else:
        result = V.String(text.data.replace(_str(what), _str(replacement)))
    if setter is not None:
        setter(result)
    return result


def _split(ev, args):
    """``split`` - split a collection/string into parts (see Collections.nim)."""
    text = args[0]
    by = attr(ev, "by", None)
    words = attr_true(ev, "words")
    lines = attr_true(ev, "lines")
    whitespace = attr_true(ev, "whitespace")
    regex = attr(ev, "regex", None)
    every = attr(ev, "every", None)
    at = attr(ev, "at", None)
    want_path = attr_true(ev, "path")

    if every is not None:
        n = to_int(every)
        if n <= 0:
            n = 1
        if text.kind in ("block", "inline"):
            items = list(text.data)
            return V.Block([V.Block(items[i:i + n]) for i in range(0, len(items), n)])
        s = _str(text)
        return V.Block([V.String(s[i:i + n]) for i in range(0, len(s), n)])

    if at is not None:
        index = to_int(at)
        if text.kind in ("block", "inline"):
            items = list(text.data)
            return V.Block([V.Block(items[:index]), V.Block(items[index:])])
        s = _str(text)
        return V.Block([V.String(s[:index]), V.String(s[index:])])

    s = _str(text)

    if by is not None:
        if isinstance(by, V.Regex):
            return V.Block([V.String(x) for x in by.compiled.split(s)])
        if by.kind in ("block", "inline"):
            # split on any of the given separators (longest match first)
            seps = sorted((_str(sep) for sep in by.data), key=len, reverse=True)
            seps = [x for x in seps if x]
            if not seps:
                return V.Block([V.String(s)])
            pattern = "|".join(_re.escape(x) for x in seps)
            parts = _re.split(pattern, s)
            return V.Block([V.String(x) for x in parts if x != ""])
        sep = _str(by)
        if sep == "":
            return V.Block([V.String(c) for c in s])
        return V.Block([V.String(x) for x in s.split(sep)])

    if regex is not None:
        pattern = regex.compiled if isinstance(regex, V.Regex) else _re.compile(_str(regex))
        return V.Block([V.String(x) for x in pattern.split(s)])
    if words:
        return V.Block([V.String(x) for x in s.split()])
    if lines:
        return V.Block([V.String(x) for x in s.splitlines()])
    if whitespace:
        return V.Block([V.String(x) for x in s.split()])
    if want_path:
        import os

        return V.Block([V.String(part) for part in s.split(os.sep) if part])
    # no criteria: split into single-character strings
    return V.Block([V.String(c) for c in s])


@impl("split")
def _split_builtin(ev, args):
    return _split(ev, args)


@impl("join")
def _join(ev, args):
    value = args[0]
    items = value.data if value.kind in ("block", "inline") else list(seq_of(value))
    with_ = attr(ev, "with", None)
    if attr_true(ev, "path"):
        import os

        sep = with_.data if with_ is not None else "/"
        return V.String(sep.join(_str(x) for x in items))
    if with_ is None:
        return V.String("".join(_str(x) for x in items))
    sep = _str(with_)
    return V.String(sep.join(_str(x) for x in items))


@builtin("alphabet", arity=1)
def _alphabet(ev, args):
    text = _str(args[0])
    return V.Logical(text.isalpha())


@builtin("ascii?", arity=1)
def _ascii_q(ev, args):
    text = _str(args[0])
    return V.Logical(all(ord(c) < 128 for c in text))


@builtin("whitespace?", arity=1)
def _whitespace_q(ev, args):
    return V.Logical(_str(args[0]).isspace())


@builtin("prefix?", arity=2)
def _prefix_q(ev, args):
    text, prefix = _str(args[0]), _str(args[1])
    return V.Logical(text.startswith(prefix))


@builtin("suffix?", arity=2)
def _suffix_q(ev, args):
    text, suffix = _str(args[0]), _str(args[1])
    return V.Logical(text.endswith(suffix))


@builtin("startsWith", arity=2)
def _starts_with(ev, args):
    return _prefix_q(ev, args)


@builtin("endsWith", arity=2)
def _ends_with(ev, args):
    return _suffix_q(ev, args)


@builtin("levenshtein", arity=2)
def _levenshtein(ev, args):
    a, b = _str(args[0]), _str(args[1])
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return V.Integer(previous[-1])


@builtin("jaro", arity=2)
def _jaro(ev, args):
    a, b = _str(args[0]), _str(args[1])
    if a == b:
        return V.Floating(1.0)
    if not a or not b:
        return V.Floating(0.0)
    window = max(len(a), len(b)) // 2 - 1
    a_matched = [False] * len(a)
    b_matched = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_matched[j] and b[j] == ca:
                a_matched[i] = b_matched[j] = True
                matches += 1
                break
    if matches == 0:
        return V.Floating(0.0)
    t = 0
    k = 0
    for i, ca in enumerate(a):
        if a_matched[i]:
            while not b_matched[k]:
                k += 1
            if ca != b[k]:
                t += 1
            k += 1
    t //= 2
    return V.Floating((matches / len(a) + matches / len(b) + (matches - t) / matches) / 3)


@impl("indent")
def _indent(ev, args):
    text = _str(args[0])
    n = to_int(args[1]) if len(args) > 1 else 4
    padding = " " * n
    return V.String("\n".join(padding + line for line in text.split("\n")))


@impl("outdent")
def _outdent(ev, args):
    text = _str(args[0])
    from ..parser import dedent

    return V.String(dedent(text))


@builtin("wordwrap", arity=1)
def _wordwrap(ev, args):
    import textwrap

    text = _str(args[0])
    width = attr(ev, "at", None)
    w = to_int(width) if width is not None else 80
    return V.String(textwrap.fill(text, w))


def _regex_of(value):
    if isinstance(value, V.Regex):
        return value.compiled
    if isinstance(value, V.Char):
        return _re.compile(_re.escape(value.data))
    return _re.compile(V.to_string(value))


def _range_of(match, group=0):
    start, stop = match.span(group)
    return V.Range(start, stop - 1, 1)


@builtin("match", arity=2,
         attrs=["once", "count", "capture", "named", "bounds", "in", "full"])
def _match(ev, args):
    text = _str(args[0])
    pattern = _regex_of(args[1])
    window = attr(ev, "in", None)
    start, stop = 0, len(text)
    if window is not None and window.kind == "range":
        start = max(0, to_int(window.start))
        stop = min(len(text), to_int(window.stop) + 1)
        text = text[:stop]
    matches = list(pattern.finditer(text, start))
    if attr_true(ev, "once"):
        matches = matches[:1]
    if attr_true(ev, "count"):
        return V.Integer(len(matches))
    if attr_true(ev, "bounds"):
        return V.Block([_range_of(m) for m in matches])
    if attr_true(ev, "capture"):
        out = []
        for m in matches:
            groups = m.groups()
            if attr_true(ev, "named"):
                out.append(V.Dictionary({k: V.String(v or "") for k, v in m.groupdict().items()}))
            elif len(groups) > 1:
                out.append(V.Block([V.String(g or "") for g in groups]))
            elif groups:
                out.append(V.String(groups[0] or ""))
            else:
                out.append(V.String(m.group(0)))
        return V.Block(out)
    return V.Block([V.String(m.group(0)) for m in matches])


@builtin("match?", arity=2)
def _match_q(ev, args):
    text, pattern = _str(args[0]), args[1]
    compiled = pattern.compiled if isinstance(pattern, V.Regex) else _re.compile(_str(pattern))
    match = compiled.search(text)
    if match is None:
        return V.Logical(False)
    if attr_true(ev, "capture"):
        groups = list(match.groups())
        if groups:
            return V.Block([V.String(g or "") for g in groups])
        return V.String(match.group(0))
    return V.Logical(True)


_XML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;",
                '"': "&quot;", "'": "&apos;"}


@builtin("escape", arity=1, attrs=["xml", "html", "regex", "json"])
def _escape(ev, args):
    if attr_true(ev, "xml") or attr_true(ev, "html"):
        text = V.to_string(args[0])
        return V.String("".join(_XML_ESCAPES.get(ch, ch) for ch in text))
    text = _str(args[0])
    return V.String(text.encode("unicode_escape").decode("ascii"))


@builtin("unescape", arity=1)
def _unescape(ev, args):
    text = _str(args[0])
    return V.String(text.encode("ascii", "backslashreplace").decode("unicode_escape"))


@builtin("encode", arity=1, attrs=["url", "spaces", "slashes", "from", "to", "codec"])
def _encode(ev, args):
    if attr_true(ev, "url"):
        return V.String(_url_encode(_str(args[0]), attr_true(ev, "spaces")))
    codec = attr(ev, "codec", None)
    name = codec.data if isinstance(codec, V.String) else "base64"
    return V.String(_b64(args[0], name, True))


_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")


def _url_encode(text: str, encode_spaces: bool = False) -> str:
    out = []
    for ch in text:
        if ch in _UNRESERVED:
            out.append(ch)
        elif ch == " ":
            out.append("%20" if encode_spaces else "+")
        else:
            out.append("".join("%%%02X" % b for b in ch.encode("utf-8")))
    return "".join(out)


def _b64(value, codec, encode):
    import base64
    import binascii

    text = _str(value) if value.kind == "string" else V.to_string(value)
    if codec in ("base64",):
        return base64.b64encode(text.encode()).decode() if encode else base64.b64decode(text).decode()
    if codec in ("hex",):
        return text.encode().hex().upper() if encode else bytes.fromhex(text).decode()
    if codec in ("url",):
        from urllib.parse import quote, unquote

        return quote(text) if encode else unquote(text)
    if codec in ("utf-8", "utf8"):
        return text
    return text


@builtin("decode", arity=1, attrs=["url", "codec"])
def _decode(ev, args):
    if attr_true(ev, "url"):
        from urllib.parse import unquote_plus

        return V.String(unquote_plus(_str(args[0])))
    codec = attr(ev, "codec", None)
    name = codec.data if isinstance(codec, V.String) else "base64"
    return V.String(_b64(args[0], name, False))


@builtin("format", arity=1)
def _format(ev, args):
    return V.String(_str(args[0]))


# ---------------------------------------------------------------------------
# rendering:  ~"Hello |name|"
# ---------------------------------------------------------------------------
@impl("render")
def _render(ev, args):
    value = args[0]
    if value.kind != "string":
        fail("cannot render non-string", "Type Error")
    text = value.data
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "|":
            j = i + 1
            depth = 1
            buf = []
            while j < n:
                if text[j] == "|":
                    break
                buf.append(text[j])
                j += 1
            code = "".join(buf)
            out.append(_render_expr(ev, code))
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return V.String("".join(out))


def _render_expr(ev, code: str) -> str:
    from .. import parser as P
    from .. import ast as A

    src = code.strip()
    if not src:
        return ""
    block = P.parse(src)
    tree = A.build(block, ev.ctx.library)
    try:
        value = ev.eval_node(tree)
    except ArturoError:
        raise
    if value is V.VOID:
        return ""
    return V.print_str(value)


@builtin("string", arity=1)
def _string(ev, args):
    return V.String(V.to_string(args[0]))
