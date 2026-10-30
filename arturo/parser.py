"""
parser.py - Arturo lexer/parser.

This is a faithful port of Arturo's ``src/vm/parse.nim``: the parser turns
source text into a *Block of values* (Arturo's "code is data" model).  No
abstract syntax tree is built here - that is the job of :mod:`arturo.ast`.

The token stream is a single :class:`~arturo.values.Block` whose items are
ordinary Arturo values, plus a few parser-only markers:

* ``Word`` / ``Literal`` / ``Label`` / ``Path`` / ``PathLabel``
* ``Attribute`` / ``AttributeLabel``
* ``Symbol``   (``+``, ``->``, ``|``, ...)
* literals: integers, floats, strings, blocks, inline blocks, dictionaries...
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from . import values as V


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
# Longest-match table (Arturo's own hand-written scanner produces exactly
# these multi-character symbols).
SYMBOLS = {
    '\\': 'backslash',
    '\\\\': 'doublebackslash',
    '######': 'sextuplesharp',
    '#####': 'quintuplesharp',
    '<<->>': 'arrowdoubleboth',
    '<<=>>': 'thickarrowdoubleboth',
    '>>-<<': 'reversearrowdoubleboth',
    '####': 'quadruplesharp',
    '<-->': 'longarrowboth',
    '<==>': 'longthickarrowboth',
    '###': 'triplesharp',
    '-->': 'longarrowright',
    '-<<': 'reversearrowdoubleleft',
    '->>': 'arrowdoubleright',
    '...': 'longellipsis',
    '<--': 'longarrowleft',
    '<->': 'arrowboth',
    '<<-': 'arrowdoubleleft',
    '<<<': 'triplearrowleft',
    '<<=': 'thickarrowdoubleleft',
    '<==': 'longthickarrowleft',
    '<=>': 'thickarrowboth',
    '<|>': 'triangleboth',
    '<~>': 'tildeboth',
    '==>': 'longthickarrowright',
    '=>>': 'thickarrowdoubleright',
    '>-<': 'reversearrowboth',
    '>>-': 'reversearrowdoubleright',
    '>>>': 'triplearrowright',
    '!!': 'doubleexclamation',
    '##': 'doublesharp',
    '**': 'doubleasterisk',
    '++': 'doubleplus',
    '--': 'doubleminus',
    '-:': 'minuscolon',
    '-<': 'reversearrowleft',
    '->': 'arrowright',
    '..': 'ellipsis',
    './': 'dotslash',
    '/%': 'slashpercent',
    '//': 'doubleslash',
    '::': 'doublecolon',
    ':=': 'colonequal',
    '<-': 'arrowleft',
    '<:': 'lesscolon',
    '<<': 'doublearrowleft',
    '<=': 'thickarrowleft',
    '<>': 'lessgreater',
    '<|': 'triangleleft',
    '<~': 'tildeleft',
    '=<': 'equalless',
    '==': 'doubleequal',
    '=>': 'thickarrowright',
    '=~': 'approxequal',
    '>-': 'reversearrowright',
    '>:': 'greatercolon',
    '>=': 'greaterequal',
    '>>': 'doublearrowright',
    '??': 'doublequestion',
    '|-': 'turnstile',
    '|=': 'doubleturnstile',
    '|>': 'triangleright',
    '||': 'doublepipe',
    '~>': 'tilderight',
    '!': 'exclamation',
    '#': 'sharp',
    '$': 'dollar',
    '%': 'percent',
    '&': 'ampersand',
    '*': 'asterisk',
    '+': 'plus',
    '-': 'minus',
    '/': 'slash',
    ':': 'colon',
    '<': 'lessthan',
    '=': 'equal',
    '>': 'greaterthan',
    '?': 'question',
    '@': 'at',
    '^': 'caret',
    '_': 'underscore',
    '|': 'pipe',
    '~': 'tilde',
    '«': 'lcurly',
    '¬': 'logicalnot',
    '²': 'squared',
    '»': 'rcurly',
    '←': 'arrowleft',
    '→': 'arrowright',
    '↔': 'arrowboth',
    '⇒': 'thickarrowright',
    '∅': 'slashedzero',
    '∈': 'element',
    '∉': 'notelement',
    '∏': 'product',
    '∑': 'summation',
    '∞': 'infinite',
    '∧': 'logicaland',
    '∨': 'logicalor',
    '∩': 'intersection',
    '∪': 'union',
    '≠': 'lessgreater',
    '≤': 'thickarrowleft',
    '≥': 'greaterequal',
    '⊂': 'subset',
    '⊃': 'superset',
    '⊆': 'subsetorequal',
    '⊇': 'supersetorequal',
    '⊻': 'logicalxor',
    '⊼': 'logicalnand',
}

# symbol text -> (function name, is_infix)  [extracted from src/library/*.nim]
INFIX_ALIASES = {
    "%": "mod", "*": "mul", "+": "add", "++": "append", "-": "sub",
    "--": "remove", "-->": "convert", "..": "range", "/": "div",
    "/%": "divmod", "//": "fdiv", ":": "let", ":=": "conforms?",
    "<": "less?", "<=>": "between?", "<>": "notEqual?", "=": "equal?",
    "=<": "lessOrEqual?", ">": "greater?", ">=": "greaterOrEqual?",
    ">>": "write", "?": "switch", "??": "coalesce", "^": "pow",
    "∈": "in?", "∧": "and?", "∨": "or?", "⊆": "subset?", "⊇": "superset?",
    "⊻": "xor?", "⊼": "nand?", "≤": "lessOrEqual?", "≥": "greaterOrEqual?",
    "≠": "notEqual?", "→": "convert", "←": "convert",
}
PREFIX_ALIASES = {
    "#": "dictionary", "$": "function", "./": "relative", "<<": "read",
    "<=": "dup", "@": "array", "~": "render", "¬": "not?", "∏": "product",
    "∑": "sum",
}

# Symbols that are *structural* (handled by the AST builder, never aliased)
STRUCTURAL = {"->", "=>", "|", "::", "!", "~>", "<~", "<~>", "|>", "<|", "<|>",
              "->>", "-->", "<--", "==>", "<==", "?"}
# NOTE: "?" *is* aliased (switch) - it is removed from STRUCTURAL below.
STRUCTURAL.discard("?")

LETTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = set("0123456789")
PERMITTED_ID_START = LETTERS | {"_"}
PERMITTED_ID_IN = PERMITTED_ID_START | DIGITS
PERMITTED_QTY = LETTERS | DIGITS | {".", "/"}
SYMBOL_CHARS = set("~!@#$%^&*-=+<>/|?")


class ParseError(Exception):
    def __init__(self, message, line=0):
        super().__init__(f"[line {line}] {message}")


# ---------------------------------------------------------------------------
# String helpers
# ---------------------------------------------------------------------------
def dedent(text: str) -> str:
    """Arturo's ``dedented=true`` string normalisation (indentation stripped)."""
    lines = text.split("\n")
    if len(lines) == 1:
        return text.strip()
    # drop leading/trailing empty lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    indents = [len(l) - len(l.lstrip(" \t")) for l in lines if l.strip()]
    common = min(indents) if indents else 0
    out = []
    for l in lines:
        out.append(l[common:] if len(l) > common else l.lstrip())
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class Parser:
    def __init__(self, source: str):
        self.src = source
        self.pos = 0
        self.line = 1
        self.n = len(source)

    # -- low level -------------------------------------------------------
    def _ch(self, offset: int = 0) -> str:
        p = self.pos + offset
        return self.src[p] if 0 <= p < self.n else "\0"

    def _at_end(self) -> bool:
        return self.pos >= self.n

    def _adv(self, count: int = 1) -> None:
        for _ in range(count):
            if self.pos < self.n:
                if self.src[self.pos] == "\n":
                    self.line += 1
                self.pos += 1

    # -- entry point -----------------------------------------------------
    def parse(self) -> V.Block:
        block = self._parse_block(0, is_sub_block=False, is_sub_inline=False)
        return block

    # -- whitespace / comments -------------------------------------------
    def _skip(self) -> None:
        while True:
            ch = self._ch()
            if ch in (" ", "\t", "\r", "\n"):
                self._adv()
            elif ch == ";":
                # `;; ...` on its own is a doc string - skip the whole line(s)
                if self._ch(1) == ";":
                    self._adv(2)
                    while not self._at_end() and self._ch() != "\n":
                        self._adv()
                else:
                    while not self._at_end() and self._ch() != "\n":
                        self._adv()
            elif ch == "#" and self._ch(1) == "!":
                while not self._at_end() and self._ch() != "\n":
                    self._adv()
            else:
                return

    # -- block -----------------------------------------------------------
    def _parse_block(self, level: int, is_sub_block: bool,
                     is_sub_inline: bool) -> V.Block:
        cls = V.Inline if is_sub_inline else V.Block
        block = cls()
        while True:
            self._skip()
            if self._at_end():
                if level != 0:
                    if is_sub_block:
                        raise ParseError("Missing closing square bracket", self.line)
                    raise ParseError("Missing closing parenthesis", self.line)
                break
            ch = self._ch()

            if ch == "]":
                if is_sub_block:
                    self._adv()
                    break
                raise ParseError("Stray closing square bracket", self.line)
            if ch == ")":
                if is_sub_inline:
                    self._adv()
                    break
                raise ParseError("Stray closing parenthesis", self.line)
            if ch == "}":
                raise ParseError("Stray closing curly bracket", self.line)

            tok = self._parse_token(level)
            if tok is not None:
                tok.ln = self.line
                block.data.append(tok)

        return block

    # -- single token ----------------------------------------------------
    def _parse_token(self, level: int) -> Optional[V.Value]:
        ch = self._ch()
        ln = self.line

        if ch == '"':
            return V.String(self._parse_string())
        if ch == "{":
            return self._parse_curly()
        if ch == "'":
            return self._parse_tick(level)
        if ch == "`":
            self._adv()
            start = self.pos
            while self._ch() in PERMITTED_QTY:
                self._adv()
            return V.Unit(self.src[start:self.pos])
        if ch == ":":
            self._adv()
            name = self._parse_identifier()
            if not name:
                if self._ch() == ":":
                    self._adv()
                    return V.Symbol("::")
                if self._ch() == "=":
                    self._adv()
                    return V.Symbol(":=")
                return V.Symbol(":")
            return V.Type(name)
        if ch in DIGITS:
            return self._parse_number()
        if ch == "\\":
            if self._is_id_start(self._ch(1)) or self._ch(1) == "[":
                root = V.Word("this")
                return self._parse_path(root, level)
            if self._ch(1) == "\\":
                self._adv(2)
                return V.Symbol("\\\\")
            if self._ch(1) == "/":
                self._adv(2)
                return V.Symbol("∨")
            self._adv()
            return V.Symbol("\\")
        if ch == "ø":
            self._adv()
            return V.Symbol("ø")
        if ch in PERMITTED_ID_START or (ord(ch) > 127 and ch.isalpha()):
            return self._parse_word(level)
        if ch == ".":
            if self._ch(1) == ".":
                if self._ch(2) == ".":
                    self._adv(3)
                    return V.Symbol("...")
                self._adv(2)
                return V.Symbol("..")
            if self._ch(1) == "/":
                self._adv(2)
                return V.Symbol("./")
            self._adv()
            name = self._parse_identifier()
            if self._ch() == ":":
                self._adv()
                return V.AttributeLabel(name)
            return V.Attribute(name)
        if ch == "[":
            self._adv()
            return self._parse_block(level + 1, is_sub_block=True, is_sub_inline=False)
        if ch == "(":
            self._adv()
            return self._parse_block(level + 1, is_sub_block=False, is_sub_inline=True)
        if ch == "«":
            return self._parse_smart_quote()
        if ch == "ø":
            self._adv()
            return V.Symbol("ø")
        if ch == "¬":
            self._adv()
            return V.Symbol("¬")
        if ch == "∅":
            self._adv()
            return V.Symbol("∅")
        if ch in "∞∑∏∩∪⊂⊃⊆⊇∈∉∧∨⊻⊼≤≥≠→←↔⇒":
            self._adv()
            return V.Symbol(ch)
        if ch in SYMBOL_CHARS:
            return self._parse_symbol(level)
        if ch == ",":
            self._adv()
            return None
        if ch == "-":
            return self._parse_symbol(level)

        # unknown character: skip it (mirrors Arturo's permissive lexer)
        self._adv()
        return None

    def _is_id_start(self, ch: str) -> bool:
        return ch in PERMITTED_ID_START or (ch and ord(ch) > 127 and ch.isalpha())

    def _is_id_continue(self, ch: str) -> bool:
        return ch in PERMITTED_ID_IN or (ch and ord(ch) > 127 and ch.isalnum())

    # ------------------------------------------------------------------
    # Identifiers / words
    # ------------------------------------------------------------------
    def _parse_identifier(self, also_add_current: bool = False) -> str:
        out = []
        if also_add_current:
            if self._ch() in PERMITTED_ID_START:
                out.append(self._ch())
                self._adv()
            elif ord(self._ch()) > 127 and self._ch().isalpha():
                out.append(self._ch())
                self._adv()
        initial = len(out)
        while self._is_id_continue(self._ch()):
            out.append(self._ch())
            self._adv()
        if self._ch() == "?" and len(out) != initial:
            out.append("?")
            self._adv()
        return "".join(out)

    def _parse_word(self, level: int) -> V.Value:
        name = self._parse_identifier(also_add_current=True)
        if name == "_":
            return V.Symbol("_")
        if self._ch() == ":":
            self._adv()
            return V.Label(name)
        if self._ch() == "\\":
            nxt = self._ch(1)
            if self._is_id_start(nxt) or nxt in DIGITS or nxt == "[":
                path = self._parse_path(V.Word(name), level)
                if self._ch() == ":":
                    self._adv()
                    return V.PathLabel(path.data)
                return path
            self._adv()
            return V.Symbol("\\")
        return V.Word(name)

    def _parse_tick(self, level: int) -> V.Value:
        initial = self.pos
        self._adv()  # consume '
        name = self._parse_identifier(also_add_current=False)
        if not name:
            # '  +  -> symbol literal, or char
            ch = self._ch()
            if ch in SYMBOL_CHARS or ch in "¬∅∞∑∏":
                sym = self._parse_symbol(level)
                if isinstance(sym, V.Symbol):
                    if sym.data == "\\" and self._ch() in "nrtbfvaexuU0123456789":
                        self.pos = initial
                        text = self._parse_string(stopper="'")
                        return V.Char(text)
                    if self._ch() == "'":
                        self.pos = initial
                        text = self._parse_string(stopper="'")
                        return V.Char(text)
                    return V.Symbol(sym.data)
            self.pos = initial
            text = self._parse_string(stopper="'")
            return V.Char(text)

        if self._ch() == "\\":
            nxt = self._ch(1)
            if self._is_id_start(nxt) or nxt in DIGITS:
                path = self._parse_path(V.Word(name), level, as_literal=True)
                return V.PathLiteral(path.data)
            self._adv()
            return V.Symbol("\\")
        if self._ch() == "'":
            self._adv()
            return V.Char(name)
        return V.Literal(name)

    def _parse_path(self, root: V.Value, level: int, as_literal: bool = False) -> V.Path:
        parts: List[V.Value] = [root]
        while self._ch() == "\\":
            self._adv()
            if self._is_id_start(self._ch()):
                parts.append(V.Literal(self._parse_identifier(also_add_current=True)))
            elif self._ch() in DIGITS:
                num = self._parse_number()
                parts.append(num)
            elif self._ch() == "[":
                if as_literal:
                    break
                self._adv()
                sub = self._parse_block(level + 1, is_sub_block=True, is_sub_inline=False)
                parts.append(sub)
            elif self._ch() == "-" and self._ch(1) in DIGITS:
                self._adv()
                num = self._parse_number()
                parts.append(V.Integer(-num.data))
            else:
                break
        return V.Path(parts)

    # ------------------------------------------------------------------
    # numbers
    # ------------------------------------------------------------------
    def _parse_number(self, in_path: bool = False) -> V.Value:
        start = self.pos
        if not in_path and self._ch() == "0" and self._ch(1) in "xXbBoO":
            marker = self._ch(1).lower()
            self._adv(2)
            if marker == "x":
                allowed = set("0123456789abcdefABCDEF")
                base = 16
            elif marker == "b":
                allowed = set("01")
                base = 2
            else:
                allowed = set("01234567")
                base = 8
            digits_start = self.pos
            while self._ch() in allowed:
                self._adv()
            text = self.src[digits_start:self.pos]
            if text:
                return V.Integer(int(text, base))
            self.pos = start
            self.line = self.line  # unchanged
        digits_start = self.pos
        while self._ch() in DIGITS:
            self._adv()
        has_dot = False
        if self._ch() == "." and self._ch(1) in DIGITS:
            has_dot = True
            self._adv()
            while self._ch() in DIGITS:
                self._adv()
            if self._ch() == "." and self._ch(1) in DIGITS:
                # version literal
                self._adv()
                while self._ch() in DIGITS:
                    self._adv()
                while self._ch() in LETTERS | DIGITS | {"+", "-", "."}:
                    self._adv()
                return V.Version(self.src[digits_start:self.pos])

        text = self.src[digits_start:self.pos]

        if has_dot:
            if self._ch() == "`":
                self._adv()
                unit_start = self.pos
                while self._ch() in PERMITTED_QTY:
                    self._adv()
                return V.Quantity(V.Floating(float(text)), self.src[unit_start:self.pos])
            if self._ch() in ("e", "E") and (self._ch(1) in DIGITS or self._ch(1) in "+-"):
                self._adv()
                exp_start = self.pos
                if self._ch() in "+-":
                    self._adv()
                while self._ch() in DIGITS:
                    self._adv()
                return V.Floating(float(text + "e" + self.src[exp_start:self.pos]))
            return V.Floating(float(text))

        if self._ch() == "`":
            self._adv()
            unit_start = self.pos
            while self._ch() in PERMITTED_QTY:
                self._adv()
            return V.Quantity(V.Integer(int(text)), self.src[unit_start:self.pos])
        if self._ch() == ":" and self._ch(1) in DIGITS:
            self._adv()
            den_start = self.pos
            while self._ch() in DIGITS:
                self._adv()
            den = int(self.src[den_start:self.pos])
            if self._ch() == "`":
                self._adv()
                unit_start = self.pos
                while self._ch() in PERMITTED_QTY:
                    self._adv()
                return V.Quantity(V.Rational(int(text), den), self.src[unit_start:self.pos])
            return V.Rational(int(text), den)
        if self._ch() == "x" and self._ch(1) in DIGITS:
            # complex: 2x3i
            self._adv()
            imag_start = self.pos
            while self._ch() in DIGITS:
                self._adv()
            if self._ch() == "i":
                self._adv()
                return V.Complex(float(text), float(self.src[imag_start:self.pos]))
            self.pos = start + len(text)
            return V.Integer(int(text))
        if self._ch() in ("e", "E") and (self._ch(1) in DIGITS or self._ch(1) in "+-"):
            self._adv()
            exp_start = self.pos
            if self._ch() in "+-":
                self._adv()
            while self._ch() in DIGITS:
                self._adv()
            return V.Floating(float(text + "e" + self.src[exp_start:self.pos]))
        return V.Integer(int(text))

    # ------------------------------------------------------------------
    # strings
    # ------------------------------------------------------------------
    def _parse_string(self, stopper: str = '"') -> str:
        start_line = self.line
        self._adv()  # opening quote
        out: List[str] = []
        in_code = False
        while True:
            ch = self._ch()
            if ch == "\0":
                raise ParseError("Unterminated string", start_line)
            if ch == stopper:
                self._adv()
                break
            if ch == "|":
                out.append("|")
                self._adv()
                in_code = not in_code
            elif ch == "\\" and not in_code:
                esc = self._ch(1)
                simple = {"\\": "\\", '"': '"', "'": "'", "/": "/", "a": "\a",
                          "b": "\b", "e": "\x1b", "f": "\f", "n": "\n", "l": "\n",
                          "r": "\r", "c": "\r", "t": "\t", "v": "\v"}
                if esc in simple:
                    out.append(simple[esc])
                    self._adv(2)
                elif esc == "x":
                    self._adv(2)
                    hexd = ""
                    for _ in range(2):
                        c = self._ch()
                        if c in "0123456789abcdefABCDEF":
                            hexd += c
                            self._adv()
                        else:
                            break
                    if hexd:
                        out.append(chr(int(hexd, 16)))
                else:
                    out.append("\\")
                    out.append(esc)
                    self._adv(2)
            elif ch in ("\n", "\r"):
                raise ParseError("Newline in quoted string", start_line)
            else:
                out.append(ch)
                self._adv()
        return "".join(out)

    def _parse_curly(self) -> V.Value:
        start_line = self.line
        self._adv()  # {
        verbatim = False
        is_regex = False
        flags = ""
        if self._ch() == "!":
            self._adv()
            while self._ch() in LETTERS:
                self._adv()
        if self._ch() == ":":
            self._adv()
            verbatim = True
        elif self._ch() == "/":
            self._adv()
            is_regex = True

        out: List[str] = []
        curlies = 1
        while True:
            ch = self._ch()
            if ch == "\0":
                raise ParseError("Unterminated string", start_line)
            if ch == "{":
                curlies += 1
                out.append(ch)
                self._adv()
            elif ch == "}":
                if not verbatim:
                    if curlies == 1:
                        self._adv()
                        break
                    curlies -= 1
                out.append(ch)
                self._adv()
            elif ch == ":" and verbatim and self._ch(1) == "}":
                self._adv(2)
                break
            elif ch == "\\" and is_regex:
                if self._ch(1) == "/":
                    out.append("/")
                    self._adv(2)
                else:
                    out.append("\\")
                    self._adv()
            elif ch == "/" and is_regex:
                if self._ch(1) == "}":
                    self._adv(2)
                    break
                if self._ch(1) in "ims":
                    while self._ch() in "ims":
                        flags += self._ch()
                        self._adv()
                    if self._ch() == "}":
                        self._adv()
                        break
                    raise ParseError("Unterminated regex", start_line)
                out.append(ch)
                self._adv()
            else:
                out.append(ch)
                self._adv()

        text = "".join(out)
        if self._ch() == ":" and not verbatim:
            self._adv()
            return V.Label(text)
        if verbatim:
            return V.String(text)
        if is_regex:
            return V.Regex(text, flags)
        return V.String(dedent(text))

    def _parse_smart_quote(self) -> V.String:
        # «« ... »»  (multi-line, fully raw)
        if self._ch(1) == "«":
            self._adv(2)
            out: List[str] = []
            while True:
                if self._at_end():
                    raise ParseError("Unterminated safe string", self.line)
                if self._ch() == "»":
                    if self._ch(1) == "»":
                        self._adv(2)
                        break
                    out.append("»")
                    self._adv()
                else:
                    out.append(self._ch())
                    self._adv()
            return V.String("".join(out))
        # « rest of line, stripped
        self._adv()
        out: List[str] = []
        while not self._at_end() and self._ch() != "\n":
            out.append(self._ch())
            self._adv()
        return V.String("".join(out).strip())

    # ------------------------------------------------------------------
    # symbols
    # ------------------------------------------------------------------
    def _parse_symbol(self, level: int) -> V.Value:
        ch = self._ch()
        # colors: #FF8800 / #red
        if ch == "#" and (self._ch(1) in LETTERS or self._ch(1) in DIGITS):
            self._adv()
            start = self.pos
            while self._ch() in LETTERS or self._ch() in DIGITS:
                self._adv()
            return V.Color(self.src[start:self.pos])
        if ch == "-" and self._ch(1) in DIGITS:
            # not a symbol: parser treats `-1` as `neg 1`
            self._adv()
            return V.Symbol("-")
        # longest match, up to 6 characters
        for length in range(6, 0, -1):
            text = self.src[self.pos:self.pos + length]
            if text in SYMBOLS:
                self._adv(length)
                name = SYMBOLS[text]
                if name.endswith("_unicode"):
                    continue
                return V.Symbol(text)
        self._adv()
        return V.Symbol(ch)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse(source: str) -> V.Block:
    return Parser(source).parse()
