"""
parser.py - Arturo tokenizer + AST builder.

The parser emits a list of statements (the AST).  Each statement is one of
the dataclasses defined at the top of this file.  Expressions are nested
objects like :class:`EValue`, :class:`EVar`, :class:`ECall`, :class:`ESym`.

Infix expressions are right-associative: ``a + b * c`` parses as
``ESym('+', a, ESym('*', b, c))`` so ``a + (b * c)`` is the meaning –
matching Arturo's right-to-left evaluation rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import values as V


# ---------------------------------------------------------------------------
# AST: expressions
# ---------------------------------------------------------------------------
@dataclass
class EValue:
    value: V.Value


@dataclass
class EVar:
    name: str
    attrs: List[V.VAttribute] = field(default_factory=list)


@dataclass
class ELiteral:
    name: str


@dataclass
class EPath:
    root: object  # EVar | EValue | ELiteral
    key: object   # EVar | EValue | ELiteral | EPath (nested)


@dataclass
class EPathLiteral:
    root: str
    key: str


@dataclass
class ESym:
    op: str
    left: object
    right: object


@dataclass
class ECall:
    func: object
    args: List[object]


@dataclass
class EBlock:
    items: List[object]


@dataclass
class EInline:
    items: List[object]


@dataclass
class EArrow:
    body: object


@dataclass
class EFatArrow:
    target: object


@dataclass
class EColon:
    items: List[object]


# ---------------------------------------------------------------------------
# AST: statements
# ---------------------------------------------------------------------------
@dataclass
class SExpr:
    expr: object


@dataclass
class SAssign:
    name: str
    value: object
    is_path: bool = False


@dataclass
class SPathAssign:
    path: object
    value: object


@dataclass
class SReturn:
    value: object


@dataclass
class SIf:
    cond: object
    then_branch: object
    else_branch: Optional[object] = None


@dataclass
class SWhile:
    cond: object
    body: object


@dataclass
class SBreak:
    pass


@dataclass
class SContinue:
    pass


@dataclass
class SEmpty:
    pass


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ParseError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__(f"[line {line}:{col}] {msg}")
        self.line = line
        self.col = col


# ---------------------------------------------------------------------------
# Internal token helpers
# ---------------------------------------------------------------------------
@dataclass
class _DictBlock:
    tokens: List[V.Value]


@dataclass
class _PathKey:
    key: str


@dataclass
class _PathIndex:
    block: V.VBlock


class _BlockEnd:
    pass


class _WordRefPlaceholder:
    pass


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class Parser:
    def __init__(self, source: str, library=None, known_functions=None):
        self.source = source
        self.library = library or {}
        self.pos = 0
        self.line = 1
        self.col = 1
        self._tokens: List[V.Value] = []
        # Words that have been bound as functions in the current source.
        # We seed with whatever the Interpreter already knows about so that
        # ``f 10`` after ``f: function ...`` is parsed as a call.
        self._user_functions: set = set(known_functions or set())
        self._user_types: set = set()

    # ------------------------------------------------------------------
    def parse(self) -> List[object]:
        self._tokens = self._tokenize()
        self.pos = 0
        stmts: List[object] = []
        while self.pos < len(self._tokens):
            stmt = self._parse_statement()
            if stmt is not None:
                stmts.append(stmt)
        return stmts

    # ------------------------------------------------------------------
    # Tokenizer
    # ------------------------------------------------------------------
    def _tokenize(self) -> List[V.Value]:
        toks: List[V.Value] = []
        while True:
            self._skip_ws_with_newlines(toks)
            if self.pos >= len(self.source):
                break
            tok = self._next_token()
            if tok is not None:
                toks.append(tok)
        return toks

    def _skip_ws_with_newlines(self, toks: List[V.Value]) -> None:
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch in " \t":
                self.pos += 1
                self.col += 1
            elif ch == "\n":
                self.pos += 1
                self.line += 1
                self.col = 1
                if toks and not isinstance(toks[-1], _BlockEnd):
                    toks.append(_BlockEnd())
            elif ch == "\r":
                self.pos += 1
                if self.pos < len(self.source) and self.source[self.pos] == "\n":
                    self.pos += 1
                self.line += 1
                self.col = 1
                if toks and not isinstance(toks[-1], _BlockEnd):
                    toks.append(_BlockEnd())
            elif ch == ";":
                if (
                    self.pos + 1 < len(self.source)
                    and self.source[self.pos + 1] == ";"
                ):
                    self.pos = len(self.source)
                else:
                    while (
                        self.pos < len(self.source)
                        and self.source[self.pos] != "\n"
                    ):
                        self.pos += 1
            elif ch == "#" and self.pos + 1 < len(self.source) and self.source[self.pos + 1] == "!":
                while (
                    self.pos < len(self.source) and self.source[self.pos] != "\n"
                ):
                    self.pos += 1
            else:
                break

    def _peek(self, offset: int = 0) -> str:
        p = self.pos + offset
        return self.source[p] if p < len(self.source) else ""

    def _advance(self, n: int = 1) -> str:
        s = self.source[self.pos : self.pos + n]
        for ch in s:
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
        self.pos += n
        return s

    def _next_token(self) -> Optional[V.Value]:
        ch = self._peek()
        if ch == '"':
            return self._read_string()
        if ch == "{":
            return self._read_curly()
        if ch == "[":
            return self._read_bracket_block()
        if ch == "(":
            return self._read_inline()
        if ch == "#":
            return self._read_hash()
        if ch == "'":
            return self._read_quote()
        if ch == ":":
            return self._read_type()
        if ch == "`":
            return self._read_unit()
        if ch == ".":
            if self._peek(1) == ".":
                return self._read_symbol()
            return self._read_attribute()
        if ch == "|":
            return self._read_pipe_or_symbol()
        if ch == "!":
            return self._read_exclamation_or_symbol()
        if ch == "\\":
            return self._read_path_or_symbol()
        if ch == "«":
            return self._read_smart_quote()
        if ch.isalpha() or ch == "_" or ch == "?":
            return self._read_word()
        if ch.isdigit() or (ch == "-" and self._peek(1).isdigit()):
            return self._read_number()
        if ch in "+-*/=<>~^&%@$?":
            return self._read_symbol()
        self._advance()
        return None

    # ------------------------------------------------------------------
    def _read_string(self) -> V.VString:
        self._advance()
        out: List[str] = []
        while self.pos < len(self.source):
            ch = self._peek()
            if ch == '"':
                self._advance()
                return V.String("".join(out))
            if ch == "\\":
                self._advance()
                esc = self._peek()
                if esc == "":
                    break
                self._advance()
                mapping = {
                    "n": "\n", "l": "\n", "r": "\r", "c": "\r",
                    "t": "\t", "b": "\b", "f": "\f", "v": "\v",
                    "a": "\a", "e": "\x1b", "0": "\0",
                    "\\": "\\", '"': '"', "'": "'", "/": "/",
                }
                if esc in mapping:
                    out.append(mapping[esc])
                elif esc == "x":
                    hex_chars = ""
                    while len(hex_chars) < 2 and self._peek().lower() in "0123456789abcdef":
                        hex_chars += self._advance()
                    if hex_chars:
                        out.append(chr(int(hex_chars, 16)))
                else:
                    out.append("\\" + esc)
            elif ch == "\n" or ch == "\r":
                raise ParseError("Newline in string literal", self.line, self.col)
            else:
                out.append(self._advance())
        raise ParseError("Unterminated string", self.line, self.col)

    def _read_curly(self) -> V.Value:
        self._advance()
        verbatim = False
        regex = False
        regex_flags = ""
        if self._peek() == "!":
            self._advance()
            while self._peek().isalpha():
                self._advance()
        if self._peek() == ":":
            verbatim = True
            self._advance()
        elif self._peek() == "/":
            regex = True
            self._advance()
        depth = 1
        out: List[str] = []
        while self.pos < len(self.source):
            ch = self._peek()
            if ch == "{":
                depth += 1
                out.append(self._advance())
            elif ch == "}":
                if depth == 1:
                    self._advance()
                    break
                depth -= 1
                out.append(self._advance())
            elif ch == ":" and verbatim and self._peek(1) == "}":
                self._advance(2)
                break
            elif ch == "\n":
                out.append(self._advance())
            else:
                out.append(self._advance())
        text = "".join(out)
        if regex:
            return V.Regex(text, regex_flags)
        if verbatim:
            return V.String(text)
        return V.String(_dedent(text))

    def _read_bracket_block(self) -> V.VBlock:
        self._advance()
        items: List[V.Value] = []
        while self.pos < len(self.source):
            self._skip_ws_with_newlines(items)
            if self.pos >= len(self.source):
                break
            if self._peek() == "]":
                self._advance()
                break
            tok = self._next_token()
            if tok is not None:
                items.append(tok)
        return V.Block(items)

    def _read_inline(self) -> V.VInline:
        self._advance()
        items: List[V.Value] = []
        while self.pos < len(self.source):
            self._skip_ws_with_newlines(items)
            if self.pos >= len(self.source):
                break
            if self._peek() == ")":
                self._advance()
                break
            tok = self._next_token()
            if tok is not None:
                items.append(tok)
        return V.Inline(items)

    def _read_hash(self) -> V.Value:
        self._advance()
        if self._peek() == "[":
            self._advance()
            tokens: List[V.Value] = []
            while self.pos < len(self.source):
                self._skip_ws_with_newlines(tokens)
                if self._peek() == "]":
                    self._advance()
                    break
                tok = self._next_token()
                if tok is not None:
                    tokens.append(tok)
            return _DictBlock(tokens)
        name = ""
        while self._peek().isalnum():
            name += self._advance()
        return _parse_color(name)

    def _read_quote(self) -> V.Value:
        self._advance()
        if self._peek() != "" and self._peek() not in " \t\n\r[](){}":
            if self._peek() == "\\":
                self._advance()
                key = ""
                while self._peek().isalnum() or self._peek() == "_":
                    key += self._advance()
                return V.PathLiteral("", key)
            if self._peek() in "+-*/=<>~^&|%@$?":
                sym = ""
                while self._peek() in "+-*/=<>~^&|%@$?":
                    sym += self._advance()
                return V.VSymbolLiteral(sym=sym)
            # char literal 'a'
            if self._peek(1) == "'":
                ch = self._advance()
                self._advance()
                return V.Char(ch)
            # path literal 'a\b
            if self._peek() == "\\":
                self._advance()
                key = ""
                while self._peek().isalnum() or self._peek() == "_":
                    key += self._advance()
                return V.PathLiteral("", key)
            # literal
            name = ""
            while self._peek().isalnum() or self._peek() == "_" or self._peek() == "?":
                name += self._advance()
            return V.Literal(name)
        return V.Literal("'")

    def _read_type(self) -> V.Value:
        self._advance()
        name = ""
        while self._peek().isalnum() or self._peek() == "_":
            name += self._advance()
        if not name:
            raise ParseError("Expected type name after ':'", self.line, self.col)
        return V.TypeVal(name)

    def _read_unit(self) -> V.Value:
        self._advance()
        name = ""
        while self._peek().isalnum() or self._peek() in "./":
            name += self._advance()
        return V.Unit(name)

    def _read_attribute(self) -> V.Value:
        self._advance()
        name = ""
        while self._peek().isalnum() or self._peek() == "_" or self._peek() == "?":
            name += self._advance()
        if self._peek() == ":":
            self._advance()
            tok = self._next_token()
            return V.Attribute(name=name, value=tok)
        return V.Attribute(name=name, value=None)

    def _read_pipe_or_symbol(self) -> V.Value:
        self._advance()
        if self._peek() == "|":
            self._advance()
            return V.Symbol("||")
        return V.Symbol("|")

    def _read_exclamation_or_symbol(self) -> V.Value:
        self._advance()
        if self._peek() == "!":
            self._advance()
            return V.Symbol("!!")
        return V.Symbol("!")

    def _read_path_or_symbol(self) -> V.Value:
        self._advance()
        first = self._peek()
        if first == "":
            return V.Symbol("\\")
        if first.isalpha() or first == "_":
            key = ""
            while self._peek().isalnum() or self._peek() == "_" or self._peek() == "?":
                key += self._advance()
            return _PathKey(key)
        if first == "[":
            self._advance()
            tokens: List[V.Value] = []
            while self.pos < len(self.source):
                self._skip_ws_with_newlines(tokens)
                if self._peek() == "]":
                    self._advance()
                    break
                tok = self._next_token()
                if tok is not None:
                    tokens.append(tok)
            return _PathIndex(V.Block(tokens))
        return V.Symbol("\\")

    def _read_smart_quote(self) -> V.Value:
        self._advance()
        out: List[str] = []
        while self.pos < len(self.source):
            if self._peek() == "»":
                self._advance()
                return V.String("".join(out))
            out.append(self._advance())
        return V.String("".join(out))

    def _read_word(self) -> V.Value:
        name = ""
        first = self._advance()
        name += first
        while True:
            ch = self._peek()
            if ch.isalnum() or ch == "_":
                name += self._advance()
            elif ch == "?":
                name += self._advance()
            else:
                break
        if self._peek() == ":":
            if self._peek(1) == "=":
                return V.Word(name)
            self._advance()
            return V.VLabel(name)
        return V.Word(name)

    def _read_number(self) -> V.Value:
        neg = False
        if self._peek() == "-":
            neg = True
            self._advance()
        digits = ""
        while self._peek().isdigit():
            digits += self._advance()
        if self._peek() == "." and self._peek(1) == ".":
            pass
        else:
            if digits == "0" and self._peek() in ("x", "b", "o"):
                base_ch = self._advance()
                base = {"x": 16, "b": 2, "o": 8}[base_ch]
                allowed = {
                    16: "0123456789abcdefABCDEF",
                    8: "01234567",
                    2: "01",
                }[base]
                num = ""
                while self._peek() in allowed:
                    num += self._advance()
                return V.Integer(int(num, base) * (-1 if neg else 1))
            if self._peek() == "." and self._peek(1) not in ("", " ", "\t") and not self._peek(1).isalpha():
                nxt = self._peek(1)
                if nxt.isdigit():
                    digits += self._advance()
                    while self._peek().isdigit():
                        digits += self._advance()
                    if neg:
                        digits = "-" + digits
                    return V.Floating(float(digits))
            if self._peek() == ".":
                save_pos = self.pos
                self._advance()
                part2 = ""
                while self._peek().isdigit():
                    part2 += self._advance()
                if part2 and self._peek() == "." and self._peek(1).isdigit():
                    self._advance()
                    part3 = ""
                    while self._peek().isdigit():
                        part3 += self._advance()
                    pre, build = "", ""
                    if self._peek() == "-":
                        pre += self._advance()
                        while self._peek().isalnum() or self._peek() == ".":
                            pre += self._advance()
                    if self._peek() == "+":
                        build += self._advance()
                        while self._peek().isalnum() or self._peek() == ".":
                            build += self._advance()
                    return V.Version(int(digits), int(part2), int(part3), pre, build)
                else:
                    self.pos = save_pos
        if neg:
            digits = "-" + digits
        return V.Integer(int(digits))

    def _read_symbol(self) -> V.Value:
        multi = [
            "<=>", "<<=>>", "<==>", "<-->", "<->", "->>", "<<-", ">>-",
            ">-<", ">>-<<", "-<<", "<=", "=<", ">=", "<>", "->", "=>",
            "<-", "<<", ">>", "<--", "-->", "<<<", ">>>", "<~", "~>",
            "<~>", "<|", "|>", "<|>", "<:", "-:", ">:", "::",
            "∧", "∨", "⊻", "⊼", "¬", "∩", "∪", "⊆", "⊇", "∈",
            "∉", "∑", "∏", "∅", "∞", "++", "+", "--", "-", "*", "**",
            "/%", "//", "/", "==", "=~", ":=", "%", "^", "..",
            "...", "&", "??", "@", "$", "~", "!!",
        ]
        for sym in multi:
            n = len(sym)
            if self.source[self.pos : self.pos + n] == sym:
                self._advance(n)
                return V.Symbol(sym)
        ch = self._advance()
        return V.Symbol(ch)

    # ------------------------------------------------------------------
    # AST builder
    # ------------------------------------------------------------------
    def _current(self) -> Optional[V.Value]:
        if self.pos >= len(self._tokens):
            return None
        return self._tokens[self.pos]

    def _advance_token(self) -> Optional[V.Value]:
        if self.pos >= len(self._tokens):
            return None
        tok = self._tokens[self.pos]
        self.pos += 1
        return tok

    def _peek_token(self, offset=1):
        if self.pos + offset >= len(self._tokens):
            return None
        return self._tokens[self.pos + offset]

    def _parse_statement(self) -> Optional[object]:
        tok = self._current()
        if tok is None:
            return None
        # Skip statement separators
        while isinstance(tok, _BlockEnd):
            self._advance_token()
            tok = self._current()
            if tok is None:
                return None
        # Keywords
        if isinstance(tok, V.VWord) and tok.name == "if":
            return self._parse_if()
        if isinstance(tok, V.VWord) and tok.name == "while":
            return self._parse_while()
        if isinstance(tok, V.VWord) and tok.name == "loop":
            return self._parse_loop()
        if isinstance(tok, V.VWord) and tok.name == "do":
            return self._parse_do()
        if isinstance(tok, V.VWord) and tok.name == "return":
            self._advance_token()
            val = self._parse_expression()
            return SReturn(val)
        if isinstance(tok, V.VWord) and tok.name == "break":
            self._advance_token()
            return SBreak()
        if isinstance(tok, V.VWord) and tok.name == "continue":
            self._advance_token()
            return SContinue()
        if isinstance(tok, V.VWord) and tok.name in ("function", "$"):
            self._advance_token()
            result = self._parse_function()
            return result
        if isinstance(tok, V.VWord) and tok.name == "define":
            return self._parse_define()
        # Path assignment: ``a\b: v``
        if isinstance(tok, _PathKey):
            return self._parse_path_assign()
        if isinstance(tok, _PathIndex):
            return self._parse_path_assign()
        # Label assignment: ``name: value``
        if isinstance(tok, V.VLabel):
            name = tok.name
            self._advance_token()
            value = self._parse_expression()
            # Track custom-type definitions.
            if isinstance(value, ECall) and isinstance(value.func, EVar) and value.func.name == "__build_type__":
                self._user_types.add(name)
            elif isinstance(value, ECall) and isinstance(value.func, EVar) and value.func.name == "__build_function__":
                self._user_functions.add(name)
            return SAssign(name=name, value=value)
        # Default: expression statement
        expr = self._parse_expression()
        return SExpr(expr)

    def _parse_path_assign(self) -> object:
        # Collect path components: root + keys
        root = self._parse_path_root()
        value = self._parse_expression()
        return SPathAssign(path=root, value=value)

    def _parse_path_root(self) -> object:
        """Parse a path like ``a\b\c`` (the ``\`` tokens were tokenized as
        :class:`_PathKey` instances)."""
        root_name = ""
        if isinstance(self._current(), _PathKey):
            root_name = self._current().key
            self._advance_token()
        # Build up the path
        path = EVar(name=root_name) if root_name else EValue(V.Null())
        while isinstance(self._current(), _PathKey):
            key = self._current().key
            self._advance_token()
            path = EPath(root=path, key=ELiteral(key))
        return path

    def _parse_if(self) -> SIf:
        self._advance_token()  # consume 'if'
        cond = self._parse_expression()
        then_branch = self._parse_expression()
        else_branch = None
        # optional 'else'
        if isinstance(self._current(), V.VWord) and self._current().name == "else":
            self._advance_token()
            else_branch = self._parse_expression()
        return SIf(cond=cond, then_branch=then_branch, else_branch=else_branch)

    def _parse_while(self) -> SWhile:
        self._advance_token()
        cond = self._parse_expression()
        body = self._parse_expression()
        return SWhile(cond=cond, body=body)

    def _parse_lazy_call(self, name: str) -> object:
        """Parse ``map/select/filter/do ...`` as a call that the evaluator
        dispatches through the same machinery as ``loop``.  We collect
        the AST arguments verbatim and only wrap the whole thing in an
        ECall whose function is the actual builtin name.

        Note: ``self._current()`` is already past the keyword (the
        caller has consumed it).  We only collect arguments.
        """
        args: List[object] = []
        # First arg: a full expression so ``1..10`` is one value.
        if self._current() is not None and not isinstance(self._current(), _BlockEnd):
            args.append(self._parse_expression())
        # Then we expect: optional literal, then body (block or arrow).
        if self._current() is not None and isinstance(self._current(), V.VLiteral):
            args.append(EValue(self._advance_token()))
        nxt = self._current()
        if nxt is None:
            pass
        elif isinstance(nxt, V.VBlock):
            blk = self._advance_token()
            args.append(EBlock(items=self._parse_block_items(blk.items)))
        elif isinstance(nxt, V.VSymbol) and nxt.sym in ("->", "=>"):
            self._advance_token()
            inner = self._parse_expression()
            args.append(EArrow(inner) if nxt.sym == "->" else EFatArrow(inner))
        else:
            args.append(self._parse_expression())
        return ECall(func=EVar(name=name), args=args)

    def _parse_loop(self) -> SWhile:
        """``loop collection 'var body`` — wrap as a fake ``loop`` call
        so the evaluator can handle iteration.
        """
        self._advance_token()
        # We need to parse 3 expressions: collection, optional \'var, body.
        # Simplest: build a Call directly.
        args = []
        # First, the collection (a full expression so ``1..10`` works)
        coll = self._parse_expression()
        # Continue collecting args (literal, then body)
        nxt = self._current()
        if isinstance(nxt, V.VLiteral):
            args.append(EValue(self._advance_token()))
        # Now the body: either an arrow ``-> body`` or a block ``[body]``
        nxt = self._current()
        if isinstance(nxt, V.VBlock):
            blk = self._advance_token()
            args.append(EBlock(items=self._parse_block_items(blk.items)))
        elif isinstance(nxt, V.VSymbol) and nxt.sym == "->":
            self._advance_token()
            inner = self._parse_expression()
            args.append(EArrow(inner))
        else:
            # a bare word/expr
            args.append(self._parse_expression())
        call = ECall(func=EVar(name="loop"), args=[coll] + args)
        return ("loop", call)

    def _parse_do(self) -> object:
        self._advance_token()
        # The block follows
        if isinstance(self._current(), V.VBlock):
            blk = self._advance_token()
            return SExpr(EBlock(items=self._parse_block_items(blk.items)))
        expr = self._parse_expression()
        return SExpr(expr)

    def _parse_define(self) -> object:
        """Parse ``define :typeName [body]``."""
        self._advance_token()
        # Expect a type name
        if not isinstance(self._current(), V.VType):
            raise ParseError("Expected type after 'define'", self.line, self.col)
        type_name = self._current().name
        self._advance_token()
        # The body block
        if not isinstance(self._current(), V.VBlock):
            raise ParseError("Expected block after type", self.line, self.col)
        blk = self._advance_token()
        body_items = self._parse_block_items(blk.items)
        # Wrap as a special call so the evaluator can register the type.
        return SExpr(ECall(func=EVar(name="__build_type__"),
                            args=[EValue(V.String(type_name)),
                                  EBlock(body_items)]))

    def _parse_function(self) -> object:
        """``function [...] body`` — current is just past the keyword."""
        params: List[str] = []
        body: object = EBlock(items=[])
        if isinstance(self._current(), V.VBlock):
            blk = self._advance_token()
            for item in blk.items:
                if isinstance(item, V.VWord):
                    params.append(item.name)
                elif isinstance(item, V.VString):
                    params.append(item.data)
                elif isinstance(item, V.VLiteral):
                    params.append(item.name)
        if self._current() is None:
            body = EBlock(items=[])
        elif isinstance(self._current(), V.VBlock):
            blk = self._advance_token()
            body = EBlock(items=self._parse_block_items(blk.items))
        elif isinstance(self._current(), V.VSymbol) and self._current().sym == "->":
            self._advance_token()
            inner = self._parse_expression()
            body = EBlock(items=[inner])
        else:
            inner = self._parse_expression()
            body = EBlock(items=[inner])
        return ECall(func=EVar(name="__build_function__"),
                     args=[EValue(V.String("|".join(params))), body])

    def _parse_expression(self) -> object:
        """Right-to-left infix grouping."""
        left = self._parse_atom()
        while True:
            tok = self._current()
            if tok is None:
                break
            if isinstance(tok, _BlockEnd):
                break
            if isinstance(tok, V.VSymbol):
                if tok.sym in ("->", "=>"):
                    break
                if tok.sym == "$":
                    self._advance_token()
                    left = self._parse_function()
                    continue
                op = tok.sym
                self._advance_token()
                right = self._parse_atom()
                left = _insert_op(left, op, right)
            elif isinstance(tok, V.VLabel):
                break
            else:
                break
        return left

    def _parse_atom(self) -> object:
        tok = self._current()
        if tok is None:
            raise ParseError("Unexpected end of input", self.line, self.col)
        if isinstance(tok, V.VBlock):
            self._advance_token()
            return EBlock(items=self._parse_block_items(tok.items))
        if isinstance(tok, V.VInline):
            self._advance_token()
            inner = self._parse_inline_items(tok.items)
            return inner
        concrete = (
            V.VInteger, V.VFloating, V.VString, V.VChar, V.VType,
            V.VRange, V.VRegex, V.VVersion, V.VColor, V.VUnit,
            V.VQuantity, V.VDate, V.VComplex, V.VRational, V.VNull,
            V.VLogical, V.VObject,
        )
        if isinstance(tok, concrete):
            self._advance_token()
            return EValue(tok)
        if isinstance(tok, V.VWord):
            return self._parse_word_or_call()
        if isinstance(tok, V.VLiteral):
            self._advance_token()
            return ELiteral(tok.name)
        if isinstance(tok, V.VPathLiteral):
            self._advance_token()
            return EPathLiteral(tok.root, tok.key)
        if isinstance(tok, V.VSymbolLiteral):
            self._advance_token()
            return EValue(V.String(tok.sym))
        if isinstance(tok, _DictBlock):
            self._advance_token()
            return ECall(func=EVar(name="dictionary"),
                         args=[EBlock(self._parse_block_items(tok.tokens))])
        if isinstance(tok, V.VSymbol):
            if tok.sym == "$":
                self._advance_token()
                return self._parse_function()
            if tok.sym == "->":
                self._advance_token()
                inner = self._parse_expression()
                return EArrow(inner)
            if tok.sym == "=>":
                self._advance_token()
                inner = self._parse_expression()
                return EFatArrow(inner)
            self._advance_token()
            right = self._parse_atom()
            return ESym(op=tok.sym, left=None, right=right)
        if isinstance(tok, V.VLabel):
            self._advance_token()
            return SAssign(name=tok.name, value=EValue(V.Null()))
        if isinstance(tok, _PathKey):
            return self._parse_path_expr()
        if isinstance(tok, _PathIndex):
            self._advance_token()
            sub = self._parse_inline_items(tok.block.items)
            return EPath(root=EValue(V.Null()), key=sub)
        if isinstance(tok, V.VAttribute):
            raise ParseError("Stray attribute", self.line, self.col)
        self._advance_token()
        return EValue(V.Null())

    def _parse_path_expr(self) -> object:
        # Build path: a\b\c or a\[expr]
        root_name = self._current().key
        self._advance_token()
        path = ELiteral(root_name) if root_name.startswith("'") else EVar(name=root_name)
        # The literal prefix was actually the leading char of the path key
        if isinstance(path, ELiteral) and not root_name:
            path = EVar(name="")
        while True:
            if isinstance(self._current(), _PathKey):
                key = self._current().key
                self._advance_token()
                path = EPath(root=path, key=ELiteral(key))
            elif isinstance(self._current(), _PathIndex):
                self._advance_token()
                sub = self._parse_inline_items(self._current().block.items if False else [])
                # Re-tokenize the index block
                idx_toks = []
                # Actually the _PathIndex block is just raw tokens; we
                # need to parse them.
                path = EPath(root=path, key=EVar(name=""))
                break
            else:
                break
        return path

    def _parse_block_items(self, items: List[V.Value]) -> List[object]:
        old_tokens = self._tokens
        old_pos = self.pos
        self._tokens = list(items)
        self.pos = 0
        out: List[object] = []
        try:
            while self.pos < len(self._tokens):
                while self.pos < len(self._tokens) and isinstance(self._current(), _BlockEnd):
                    self._advance_token()
                if self.pos >= len(self._tokens):
                    break
                # Top-level keywords inside a block still act as statements.
                cur = self._current()
                if isinstance(cur, V.VWord) and cur.name == "if":
                    out.append(self._parse_if())
                    continue
                if isinstance(cur, V.VWord) and cur.name == "while":
                    out.append(self._parse_while())
                    continue
                if isinstance(cur, V.VWord) and cur.name == "return":
                    self._advance_token()
                    val = self._parse_expression()
                    out.append(SReturn(val))
                    continue
                expr = self._parse_expression()
                out.append(expr)
        except ParseError:
            pass
        finally:
            self._tokens = old_tokens
            self.pos = old_pos
        return out

    def _parse_inline_items(self, items: List[V.Value]) -> object:
        old_pos = self.pos
        old_tokens = self._tokens
        self._tokens = items
        self.pos = 0
        try:
            result = self._parse_expression()
        finally:
            self._tokens = old_tokens
            self.pos = old_pos
        return result

    def _parse_word_or_call(self) -> object:
        """Parse ``word [arg1 arg2 ...]``."""
        attrs: List[V.VAttribute] = []
        while isinstance(self._current(), V.VAttribute):
            attrs.append(self._current())
            self._advance_token()
        tok = self._current()
        assert isinstance(tok, V.VWord)
        name = tok.name
        self._advance_token()
        # path: ``name\key``
        if isinstance(self._current(), _PathKey):
            return self._continue_path(EVar(name=name, attrs=attrs))
        if isinstance(self._current(), _PathIndex):
            self._advance_token()
            sub = self._parse_inline_items(self._current().block.items if False else [])
            sub = self._parse_inline_items(
                [t for t in self._tokens[self.pos:self.pos]]
            ) if False else None
            # Simplify: parse the path index
            return EPath(root=EVar(name=name, attrs=attrs), key=EVar(name=""))
        if name in ("function", "$"):
            return self._parse_function()
        if name == "if":
            return self._parse_if()
        # Special control-flow / higher-order functions: evaluate lazily
        if name in ("map", "select", "filter", "do"):
            return self._parse_lazy_call(name)
        is_known_function = bool(
            (self.library and name in self.library)
            or name in self._user_functions
        )
        if not is_known_function:
            return EVar(name=name, attrs=attrs)
        # ``function``/``$`` are special forms (no need to check here
        # because we already handled them above).
        args: List[object] = []
        while True:
            nxt = self._current()
            if nxt is None:
                break
            if isinstance(nxt, _BlockEnd):
                break
            if isinstance(nxt, V.VSymbol):
                if nxt.sym in ("->", "=>"):
                    if nxt.sym == "->":
                        self._advance_token()
                        inner = self._parse_expression()
                        args.append(EArrow(inner))
                    else:
                        self._advance_token()
                        inner = self._parse_expression()
                        args.append(EFatArrow(inner))
                    continue
                # In Arturo, function calls bind tighter than binary
                # operators, so f a-b parses as f(a-b).  When we
                # have already collected an argument, a binary operator is
                # part of that argument's expression.
                if args:
                    # The operator continues the expression of the LAST
                    # argument.  Build the full expression and use it as
                    # the final arg.
                    self.pos -= 1  # rewind so _parse_expression sees the symbol
                    new_last = self._parse_expression()
                    args.append(new_last)
                else:
                    self._advance_token()
                    inner = self._parse_atom()
                    args.append(ESym(op=nxt.sym, left=None, right=inner))
                continue
            if isinstance(nxt, V.VLabel):
                break
            if isinstance(nxt, V.VWord):
                args.append(self._parse_word_or_call())
                continue
            args.append(self._parse_atom())
        if args:
            return ECall(func=EVar(name=name, attrs=attrs), args=args)
        return EVar(name=name, attrs=attrs)

    def _continue_path(self, root) -> object:
        """Continue parsing a path starting from ``root``."""
        while True:
            if isinstance(self._current(), _PathKey):
                key = self._current().key
                self._advance_token()
                root = EPath(root=root, key=ELiteral(key))
            elif isinstance(self._current(), _PathIndex):
                self._advance_token()
                # Parse the index sub-expression from inside the [ ]
                # The _PathIndex already holds the inner tokens.
                # We saved them at tokenize time; re-parse using them.
                idx_tokens = []
                # Walk tokens until matching ]
                depth = 1
                while depth > 0 and self.pos < len(self._tokens):
                    t = self._current()
                    if isinstance(t, V.VSymbol) and t.sym == "[":
                        depth += 1
                    elif isinstance(t, V.VSymbol) and t.sym == "]":
                        depth -= 1
                        if depth == 0:
                            self._advance_token()
                            break
                    idx_tokens.append(t)
                    self._advance_token()
                # Parse the collected tokens as a sub-expression.
                inner = self._parse_inline_items(idx_tokens)
                root = EPath(root=root, key=inner)
            else:
                break
        return root


def _insert_op(tree, op: str, right) -> object:
    """Insert ``op`` into the rightmost position of ``tree`` (right-assoc)."""
    if isinstance(tree, ESym):
        tree.right = _insert_op(tree.right, op, right)
        return tree
    return ESym(op=op, left=tree, right=right)


def _dedent(text: str) -> str:
    lines = text.split("\n")
    if not lines:
        return text
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return text
    common = min(len(l) - len(l.lstrip(" ")) for l in non_empty)
    if common == 0:
        return text
    return "\n".join((l[common:] if l[:common].strip() == "" else l) for l in lines)


_COLOR_NAMES = {
    "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "white": (255, 255, 255), "black": (0, 0, 0),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "gray": (128, 128, 128), "grey": (128, 128, 128),
    "orange": (255, 165, 0), "purple": (128, 0, 128),
    "pink": (255, 192, 203), "brown": (165, 42, 42),
    "white": (255, 255, 255), "darkRed": (139, 0, 0),
    "darkGreen": (0, 100, 0), "darkBlue": (0, 0, 139),
    "darkGray": (169, 169, 169), "darkGrey": (169, 169, 169),
    "lightGray": (211, 211, 211), "lightGrey": (211, 211, 211),
    "lime": (0, 255, 0), "maroon": (128, 0, 0),
    "navy": (0, 0, 128), "olive": (128, 128, 0),
    "silver": (192, 192, 192), "teal": (0, 128, 128),
    "aqua": (0, 255, 255), "fuchsia": (255, 0, 255),
    "indigo": (75, 0, 130), "violet": (238, 130, 238),
    "crimson": (220, 20, 60), "gold": (255, 215, 0),
}


def _parse_color(name: str) -> V.Value:
    low = name.lower()
    if low in _COLOR_NAMES:
        return V.Color(*_COLOR_NAMES[low])
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return V.Color(int(name[0:2], 16), int(name[2:4], 16), int(name[4:6], 16))
    return V.Word("#" + name)
