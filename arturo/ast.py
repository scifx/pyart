"""
ast.py - Arturo's AST generation (port of ``src/vm/ast.nim``).

The parser gives us a *Block of values*.  This module walks that block and
builds a tree of :class:`Node` objects with the exact semantics Arturo uses:

* calls are **arity driven**: a word with arity *n* consumes the next *n*
  values as its arguments;
* infix operators are inserted as "call branches" and therefore group
  **right-to-left** (``2 * 3 + 4`` => ``2 * (3 + 4)``);
* attributes (``.descending``, ``.with: ","``) become children of the call
  they belong to (so they are pushed on the attribute stack right before
  the call executes);
* ``->`` turns the rest of the block into an argument block;
* ``=>`` injects implicit parameters (``&`` => ``_0``, ``__`` => ``_1``...).

Nodes are evaluated in :mod:`arturo.evaluator`.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import values as V
from .library import VersionedDict
from .parser import INFIX_ALIASES, PREFIX_ALIASES, STRUCTURAL

# infix aliases registered at runtime via ``alias.infix``
DYNAMIC_INFIX: dict = VersionedDict()


class Node:
    """A node of the generated tree."""

    __slots__ = ("kind", "children", "parent", "params", "arity", "value", "name",
                 "cache", "fast", "meta")

    def __init__(self, kind: str, arity: int = -1, value=None, name: str = ""):
        self.kind = kind
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self.params = 0
        self.cache = None
        self.fast = None
        self.meta = None
        self.arity = arity
        self.value = value
        self.name = name

    # -- tree helpers ----------------------------------------------------
    def add_child(self, child: "Node") -> None:
        child.parent = self
        self.children.append(child)
        if self.kind in ("call", "store", "attribute") and child.kind not in ("newline", "attribute"):
            self.params += 1

    def add_child_front(self, child: "Node") -> int:
        idx = 0
        while idx < len(self.children) and self.children[idx].kind == "attribute":
            idx += 1
        child.parent = self
        self.children.insert(idx, child)
        if self.kind in ("call", "store", "attribute") and child.kind not in ("newline", "attribute"):
            self.params += 1
        return idx

    def __repr__(self) -> str:  # pragma: no cover
        if self.kind in ("constant", "variable", "store"):
            return f"<{self.kind} {self.value!r}>"
        return f"<{self.kind} {self.name}#{self.arity} {self.children}>"


def dump(node: Node, level: int = 0) -> str:
    pad = "   " * level
    if node.kind in ("constant",):
        return f"{pad}Constant: {V.to_string(node.value)}\n"
    if node.kind == "variable":
        return f"{pad}Variable: {node.value.data}\n"
    if node.kind == "store":
        return f"{pad}Store: {node.value.data}\n" + "".join(dump(c, level + 1) for c in node.children)
    if node.kind == "attribute":
        return f"{pad}Attribute: {node.value.data}\n" + "".join(dump(c, level + 1) for c in node.children)
    return f"{pad}Call: {node.name}<{node.arity}>\n" + "".join(
        dump(c, level + 1) for c in node.children)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
class AstBuilder:
    def __init__(self, library, syms=None):
        self.library = library
        # TmpArities: a *snapshot* of every callable's arity, exactly like
        # Arturo's ``generateAst`` does.  Entries are removed as soon as a name
        # is (re)defined as a plain value, which is what makes
        # ``maximum: max ...`` shadow the builtin ``maximum``.
        self.arities: Dict[str, int] = {
            name: fn.arity for name, fn in library.items() if isinstance(fn, V.Function)
        }
        self.arities.update(library.user_arities)
        # names that are plain values at build time shadow the builtins
        for name, value in (syms or {}).items():
            if isinstance(value, V.Function):
                self.arities[name] = value.arity
            else:
                self.arities.pop(name, None)
        self.arrow_blocks: List[list] = []
        self.pipe_parent: Optional[Node] = None
        self.block: Optional[V.Block] = None
        self.i = 0
        self.n = 0

    # -- public ----------------------------------------------------------
    def build(self, block: V.Block, as_function: bool = False) -> Node:
        root = Node("root", -1)
        self._process_block(root, block)
        _compile_node(root)
        return root

    @staticmethod
    def _constant(value: V.Value) -> Node:
        """Constants are frozen: mutating them copies first (copy-on-write)."""
        if value.kind in ("block", "inline", "dictionary", "object", "string"):
            V.freeze(value)
        return Node("constant", 0, value=value)

    # -- helpers ---------------------------------------------------------
    def _arity_of(self, name: str) -> int:
        return self.arities.get(name, -1)

    def _is_infix_symbol(self, value: V.Value) -> bool:
        return (isinstance(value, V.Symbol)
                and (value.data in INFIX_ALIASES or value.data in DYNAMIC_INFIX)
                and value.data not in ("->", "=>", "|"))

    def _rewind(self, target: Node, optimize: bool = False) -> Node:
        while target.kind in ("call", "store", "attribute") and target.params == target.arity:
            if optimize and target.kind == "store":
                self._update_arities(target)
            target = target.parent
        return target

    def _roll(self, target: Node) -> Node:
        return target.children[-1]

    # -- call construction ----------------------------------------------
    def _add_call(self, target: Node, name: str, arity: int = -1) -> Node:
        if arity == -1:
            arity = self._arity_of(name)
        node = Node("call", arity, name=name)
        if node.arity != 0:
            target.add_child(node)
            return node
        # 0-arity call: evaluate immediately (in the tree sense)
        target, idx = self._add_potential_infix(target)
        target.add_child(node)
        return self._rewind(target, optimize=True)

    def _add_potential_infix(self, target: Node):
        if self.i < self.n - 1:
            nxt = self.block.data[self.i + 1]
            if self._is_infix_symbol(nxt):
                alias = DYNAMIC_INFIX.get(nxt.data) or INFIX_ALIASES[nxt.data]
                self.i += 1
                if self.arrow_blocks:
                    self.arrow_blocks[-1].append(nxt)
                return self._add_call(target, alias), self.i
        return target, self.i

    def _add_terminal(self, target: Node, node: Node) -> Node:
        target = self._rewind(target)
        target, _ = self._add_potential_infix(target)
        target.add_child(node)
        return self._rewind(target, optimize=True)

    def _add_terminals(self, target: Node, nodes: List[Node]) -> Node:
        target = self._rewind(target)
        target, _ = self._add_potential_infix(target)
        for n in nodes:
            target.add_child(n)
        return self._rewind(target, optimize=True)

    def _add_attribute(self, target: Node, val: V.Value, is_label: bool = False) -> Node:
        node = Node("attribute", 1, value=val)
        if not is_label:
            node.add_child(self._constant(V.TRUE))
        if self.pipe_parent is not None:
            self.pipe_parent.add_child_front(node)
            return self.pipe_parent
        target.add_child(node)
        if is_label:
            return self._roll(target)
        return target

    def _add_store(self, target: Node, val: V.Label) -> Node:
        node = Node("store", 1, value=val)
        target.add_child(node)
        return node

    def _update_arities(self, store: Node) -> None:
        child = store.children[0] if store.children else None
        name = store.value.data
        if child is not None and child.kind == "call" and child.name in (
                "function", "method", "function.inline", "method.inline") and child.children:
            first = child.children[0]
            if first.kind == "constant":
                params = first.value
                if isinstance(params, V.Literal):
                    self.arities[name] = 1
                    self.library.user_arities[name] = 1
                elif isinstance(params, V.Block):
                    items = list(params.data)
                    for idx, item in enumerate(items):
                        if isinstance(item, V.Symbol) and item.data == "->":
                            items = items[:idx]
                            break
                    arity = len([p for p in items if not isinstance(p, V.Type)])
                    self.arities[name] = arity
                    self.library.user_arities[name] = arity
                else:
                    self._forget(name)
            else:
                self._forget(name)
        else:
            self._forget(name)

    def _forget(self, name: str) -> None:
        self.arities.pop(name, None)
        self.library.user_arities.pop(name, None)

    # -- paths -----------------------------------------------------------
    def _add_path(self, target: Node, val: V.Value, is_label: bool = False) -> Node:
        parts = val.data
        base = parts[0]
        base_name = base.data if isinstance(base, V.Word) else str(base)
        if self._arity_of(base_name) == 0:
            base_node = Node("call", 0, name=base_name)
        else:
            base_node = Node("variable", 0, value=base)

        for i in range(1, len(parts)):
            key = parts[i]
            if is_label and i == len(parts) - 1:
                new_node = Node("call", 3, name="set")
            else:
                new_node = Node("call", 2, name="get")
            new_node.add_child(base_node)
            if isinstance(key, V.Block):
                sub = Node("root", -1)
                sub_builder = self
                saved = (self.i, self.n, self.block)
                self._process_block(sub, key)
                self.i, self.n, self.block = saved
                for c in sub.children:
                    new_node.add_child(c)
            else:
                new_node.add_child(self._constant(key))
            base_node = new_node

        if is_label:
            target.add_child(base_node)
            target = self._roll(target)
            return target
        return self._add_terminal(target, base_node)

    # -- inline / arrows -------------------------------------------------
    def _add_inline(self, target: Node, val: V.Block) -> Node:
        sub = Node("root", -1)
        saved = (self.i, self.n, self.block)
        self._process_block(sub, val)
        self.i, self.n, self.block = saved
        return self._add_terminals(target, sub.children)

    def _add_arrow_block(self, target: Node, block: V.Block) -> Node:
        """``f -> a + 1`` : the next *statement* becomes an argument block.

        Arturo captures exactly one statement: the arrow block ends as soon as
        one expression has been completed at the root of the sub-block.
        """
        start = self.i + 1
        items = list(block.data[start:])
        consumed = 0
        if items:
            sub = V.Block(items)
            sub_root = Node("root", -1)
            saved = (self.block, self.n, self.i)
            consumed = self._process_block(sub_root, sub, stop_at_statement=True)
            self.block, self.n, self.i = saved
        arrow = V.Block(items[:consumed])
        node = self._constant(arrow)
        target = self._rewind(target)
        target, _ = self._add_potential_infix(target)
        target.add_child(node)
        target = self._rewind(target, optimize=True)
        self.i = start + consumed - 1
        return target

    def _add_thick_arrow(self, target: Node, block: V.Block) -> Node:
        """``=>`` : build an implicit-parameter block."""
        nxt = block.data[self.i + 1]
        argblock: List[V.Value] = []
        subblock: List[V.Value] = []

        if isinstance(nxt, V.Block):
            idx = 0
            found = 0
            for item in nxt.data:
                if isinstance(item, V.Symbol) and item.data == "&":
                    arg = V.Word("_" + str(found))
                    argblock.append(arg)
                    subblock.append(arg)
                    found += 1
                else:
                    subblock.append(item)
        else:
            subblock = [nxt]
            if isinstance(nxt, V.Word):
                arity = self._arity_of(nxt.data)
                if arity > 0:
                    for j in range(arity):
                        arg = V.Word("_" + str(j))
                        argblock.append(arg)
                        subblock.append(arg)

        if len(argblock) == 1:
            nodes = [self._constant(V.Literal(argblock[0].data)),
                     self._constant(V.Block(subblock))]
        else:
            nodes = [self._constant(V.Block(argblock)),
                     self._constant(V.Block(subblock))]

        target = self._rewind(target)
        target, _ = self._add_potential_infix(target)
        for nd in nodes:
            target.add_child(nd)
        self.i += 1
        return self._rewind(target, optimize=True)

    def _add_trailing_pipe(self, target: Node, block: V.Block) -> Node:
        """``expr | f`` : feed ``expr`` into ``f`` as its first argument."""
        if self.i < self.n - 1:
            nxt = block.data[self.i + 1]
            if isinstance(nxt, V.Word):
                arity = self._arity_of(nxt.data)
                if arity != -1:
                    self.i += 1
                    target = self._rewind(target)
                    if not target.children:
                        return target
                    to_wrap = target.children.pop()
                    if target.kind in ("call", "store", "attribute"):
                        target.params -= 1
                    new_call = Node("call", arity, name=nxt.data)
                    if to_wrap.kind == "store":
                        # `x: v | f` pipes `v` into f, then stores
                        inner = to_wrap.children[0]
                        new_call.add_child(inner)
                        to_wrap.children[0] = new_call
                        new_call.parent = to_wrap
                        self.pipe_parent = new_call
                        return to_wrap
                    target.add_child(new_call)
                    new_call.add_child(to_wrap)
                    self.pipe_parent = new_call
                    return new_call
        # plain pipe symbol: keep as value
        return self._add_terminal(target, self._constant(V.Symbol("|")))

    # -- main loop -------------------------------------------------------
    def _process_block(self, root: Node, block: V.Block, stop_at_statement: bool = False) -> int:
        """Build the tree for ``block`` into ``root``.

        Returns the number of consumed items (everything, or up to the end of
        the first complete statement when ``stop_at_statement`` is set).
        """
        saved_state = (self.block, self.n, self.i)
        self.block = block
        self.n = len(block.data)
        self.i = 0
        current = root
        consumed = 0

        while self.i < self.n:
            item = block.data[self.i]
            if item is None:
                self.i += 1
                continue

            if isinstance(item, V.Word):
                if self.arrow_blocks:
                    self.arrow_blocks[-1].append(item)
                if item.data == "true":
                    current = self._add_terminal(current, self._constant(V.TRUE))
                elif item.data == "false":
                    current = self._add_terminal(current, self._constant(V.FALSE))
                else:
                    arity = self._arity_of(item.data)
                    if arity != -1:
                        current = self._add_call(current, item.data, arity)
                    else:
                        current = self._add_terminal(current, Node("variable", 0, value=item))

            elif isinstance(item, V.Label):
                if self.arrow_blocks:
                    self.arrow_blocks[-1].append(item)
                current = self._add_store(current, item)

            elif isinstance(item, V.Attribute):
                current = self._add_attribute(current, item)

            elif isinstance(item, V.AttributeLabel):
                current = self._add_attribute(current, item, is_label=True)

            elif isinstance(item, V.Path):
                current = self._add_path(current, item)

            elif isinstance(item, V.PathLabel):
                current = self._add_path(current, item, is_label=True)

            elif isinstance(item, V.Inline):
                current = self._add_inline(current, item)

            elif isinstance(item, V.Symbol):
                sym = item.data
                if sym == "::":
                    rest = V.Block(list(block.data[self.i + 1:]))
                    current = self._add_terminal(current, self._constant(rest))
                    self.i = self.n
                    consumed = self.n
                    break
                elif sym == "->":
                    current = self._add_arrow_block(current, block)
                elif sym == "=>":
                    current = self._add_thick_arrow(current, block)
                elif sym == "|":
                    current = self._add_trailing_pipe(current, block)
                elif sym == "!":
                    rest = V.Block(list(block.data[self.i + 1:]))
                    do_node = Node("call", 1, name="do")
                    do_node.add_child(self._constant(rest))
                    current.add_child(do_node)
                    self.i = self.n
                    consumed = self.n
                    break
                elif sym == "ø":
                    current = self._add_terminal(current, self._constant(V.NULL))
                else:
                    if self.arrow_blocks:
                        self.arrow_blocks[-1].append(item)
                    alias = INFIX_ALIASES.get(sym) or PREFIX_ALIASES.get(sym)
                    if alias is not None:
                        arity = self._arity_of(alias)
                        if arity != -1:
                            current = self._add_call(current, alias, arity)
                        else:
                            current = self._add_terminal(current, self._constant(item))
                    else:
                        current = self._add_terminal(current, self._constant(item))
            else:
                if self.arrow_blocks:
                    self.arrow_blocks[-1].append(item)
                current = self._add_terminal(current, self._constant(item))

            self.i += 1
            consumed = self.i
            if stop_at_statement and current is root and root.children:
                break

        self.block, self.n, self.i = saved_state
        return consumed

    def _collect_arities(self, node: Node) -> None:
        if node.kind == "store":
            self._update_arities(node)
            # stored functions may themselves define functions (rare) - skip
            return
        for child in node.children:
            self._collect_arities(child)


# ---------------------------------------------------------------------------
# Fast paths: simple subtrees are compiled into plain Python closures
# ---------------------------------------------------------------------------
_SLOW_CALLS = {"else", "case", "when?", "do", "loop", "map", "select", "filter",
               "while", "until", "times", "return", "break", "continue", "ensure"}


def _int_div(x, y):
    if y > 0 and x >= 0:
        return x // y
    if y == 0:
        return None
    q = abs(x) // abs(y)
    return q if (x >= 0) == (y >= 0) else -q


def _int_mod(x, y):
    if y > 0 and x >= 0:
        return x % y
    if y == 0:
        return None
    r = abs(x) % abs(y)
    return r if x >= 0 else -r


def _int_pow(x, y):
    if y < 0:
        return None
    try:
        return x ** y
    except (OverflowError, MemoryError):
        return None


# integer / boolean fast operations: (x, y) -> python result, or None to fall
# back to the generic (slow) implementation
_INT_SPEC = {
    "add": lambda x, y: x + y,
    "sub": lambda x, y: x - y,
    "mul": lambda x, y: x * y,
    "div": _int_div,
    "mod": _int_mod,
    "pow": _int_pow,
    "equal?": lambda x, y: x == y,
    "notEqual?": lambda x, y: x != y,
    "less?": lambda x, y: x < y,
    "greater?": lambda x, y: x > y,
    "lessOrEqual?": lambda x, y: x <= y,
    "greaterOrEqual?": lambda x, y: x >= y,
}


def _dispatch(ev, node, name, args):
    """Resolve ``name`` and run it with already-evaluated ``args``.

    Like the generic call path, a call is a fresh (scoped) evaluation context:
    an enclosing ``execUnscoped`` block must not leak its value collection into
    the blocks this call runs.  Restoring the flag here is what lets the
    compiled fast paths stay enabled inside unscoped blocks.
    """
    ctx = ev.ctx
    fn = ctx.syms.get(name)
    if fn is None or not isinstance(fn, V.Function):
        fn = node.cache
        if fn is None:
            fn = ev._resolve_callable(name)
            node.cache = fn
    impl = fn.impl
    unscoped = ctx.unscoped
    if unscoped:
        ctx.unscoped = False
    try:
        if impl is not None:
            result = impl(ev, args)
        else:
            result = ev._call_user(fn, args, name)
    finally:
        if unscoped:
            ctx.unscoped = unscoped
    if result is not V.VOID:
        ctx.last_pushed = result
    return result



# ---------------------------------------------------------------------------
# Fast paths, level 2: expression subtrees compiled into real Python source
# ---------------------------------------------------------------------------
# The closures below are a hand-rolled compiler: every node becomes a Python
# function call.  For numeric code that is dominated by call overhead, so hot
# expression trees are translated into a single generated Python function
# instead - one function entry per statement, with integer arithmetic inlined
# and no intermediate boxing.
class _Uncompilable(Exception):
    pass


_INT_OPS = {"add": "+", "sub": "-", "mul": "*"}
_CMP_OPS = {"equal?": "==", "notEqual?": "!=", "less?": "<", "greater?": ">",
            "lessOrEqual?": "<=", "greaterOrEqual?": ">="}
_HELPER_OPS = {"div": "_int_div", "mod": "_int_mod", "pow": "_int_pow"}
_UNARY_OPS = {"inc": 1, "dec": -1}
_FUSABLE = set(_INT_OPS) | set(_CMP_OPS) | set(_HELPER_OPS)
# control flow that only needs its arguments passed through unchanged
_COMPILABLE_SLOW = {"if", "unless", "switch", "switch?"}
_CONST_FROZEN = ("string", "block", "inline", "dictionary", "object")


def _is_leaf(node) -> bool:
    return node.kind == "constant" or node.kind == "variable"


def _can_fuse(node) -> bool:
    """Can ``node`` be evaluated as a single unboxed Python integer?

    Comparisons are *not* fusable: their result is a Logical, so using them
    inside an arithmetic expression would silently turn Arturo's
    type-ordered comparison into a Python bool.
    """
    kind = node.kind
    if kind == "constant":
        return type(node.value) is V.Integer
    if kind == "variable":
        return True
    if kind != "call":
        return False
    children = node.children
    if node.name == "size":
        return len(children) == 1 and children[0].kind == "variable"
    if node.name == "get":
        return (len(children) == 2 and children[0].kind == "variable"
                and _is_leaf(children[1]) and _can_fuse(children[1]))
    if node.name in _UNARY_OPS:
        return len(children) == 1 and _can_fuse(children[0])
    if node.name not in _INT_OPS and node.name not in _HELPER_OPS:
        return False
    if len(children) != 2:
        return False
    if children[0].kind == "attribute" or children[1].kind == "attribute":
        return False
    if node.name in _HELPER_OPS and not _is_leaf(children[1]):
        # the guard (``y != 0``) has to be cheap enough to duplicate
        return False
    return _can_fuse(children[0]) and _can_fuse(children[1])


def _call_count(node, limit=2) -> int:
    """Number of call nodes in the subtree, saturating at ``limit``."""
    total = 1 if node.kind == "call" else 0
    for child in node.children:
        if total >= limit:
            return total
        total += _call_count(child, limit)
    return total


class _Compiler:
    """Generates the body of a Python function evaluating one AST subtree."""

    def __init__(self, prebound=None, trees=None):
        self.prebound = prebound or {}
        self.trees = trees
        self.hoist = False
        self.hoisted: List[tuple] = []
        self.lines: List[str] = []
        self.counter = 0
        self.leaf_counter = 0
        self.leaf_order: List[tuple] = []
        self.leaf_locals: dict = {}
        self.consts: List[V.Value] = []
        self.nodes: List[Node] = []
        self.depth = 1

    # -- emission helpers -------------------------------------------------
    def emit(self, text: str) -> None:
        self.lines.append("    " * self.depth + text)

    def open(self, text: str) -> None:
        self.emit(text)
        self.depth += 1

    def close(self) -> None:
        self.depth -= 1

    def tmp(self) -> str:
        self.counter += 1
        return "t%d" % self.counter

    def const(self, value) -> str:
        self.consts.append(value)
        return "_c[%d]" % (len(self.consts) - 1)

    def node_ref(self, node) -> str:
        self.nodes.append(node)
        return "_n[%d]" % (len(self.nodes) - 1)

    # -- fused integer expressions ---------------------------------------
    def fused(self, node, guards) -> str:
        kind = node.kind
        if kind == "constant":
            return repr(node.value.data)
        if kind == "variable":
            symbol = node.value.data
            pre = self.prebound.get(symbol)
            if pre is not None and pre[1] == "int":
                return pre[0]           # already an unboxed Python int
            local = self.leaf(symbol, "Int")
            return local + ".data"
        name = node.name
        if name == "size" and len(node.children) == 1 \
                and node.children[0].kind == "variable":
            local = self.leaf(node.children[0].value.data, "Seq")
            return "len(%s.data)" % local
        if name == "get":
            container = self.leaf(node.children[0].value.data, "Block")
            index = self.fused(node.children[1], guards)
            guards.append("0 <= %s < len(%s.data)" % (index, container))
            guards.append("type(%s.data[%s]) is Int" % (container, index))
            return "%s.data[%s].data" % (container, index)
        if name in _UNARY_OPS:
            operand = self.fused(node.children[0], guards)
            return "(%s %s 1)" % (operand, "+" if _UNARY_OPS[name] > 0 else "-")
        left = self.fused(node.children[0], guards)
        right = self.fused(node.children[1], guards)
        if name in _INT_OPS:
            return "(%s %s %s)" % (left, _INT_OPS[name], right)
        if name in _HELPER_OPS:
            helper = _HELPER_OPS[name]
            if name == "pow":
                guards.append("%s >= 0" % right)
            else:
                guards.append("%s != 0" % right)
            return "%s(%s, %s)" % (helper, left, right)
        return "(%s %s %s)" % (left, _CMP_OPS[name], right)

    def emit_leaf_decls(self) -> None:
        if self.hoist:
            self.hoisted.extend(self.leaf_order)
            return
        for local, symbol, _expected in self.leaf_order:
            if symbol is None:  # pre-bound local
                continue
            self.emit("%s = syms.get(%r)" % (local, symbol))
            self.open("if %s is None:" % local)
            self.emit("%s = ctx.get(%r)" % (local, symbol))
            self.close()

    def leaf(self, symbol: str, expected: str) -> str:
        """Local holding ``symbol``, checked to be of type ``expected``."""
        pre = self.prebound.get(symbol)
        if pre is not None:
            local, known = pre
            if known is expected:
                return local
            if local not in self.leaf_locals:
                self.leaf_locals[local] = local
                self.leaf_order.append((local, None, expected))
            return local
        local = self.leaf_locals.get(symbol)
        if local is None:
            local = "s%d" % self.leaf_counter
            self.leaf_counter += 1
            self.leaf_locals[symbol] = local
            self.leaf_order.append((local, symbol, expected))
        return local

    def guard(self, guards) -> str:
        hoisted = {local for local, symbol, _ in self.hoisted
                   if symbol is not None} if self.hoist else ()
        parts = []
        for local, _symbol, expected in self.leaf_order:
            if local in hoisted:
                parts.append("ok_%s" % local)
            else:
                test = _TYPE_TEST.get(expected)
                parts.append(test.format(local) if test
                             else "type(%s) is %s" % (local, expected))
        parts.extend(guards)
        return " and ".join(parts) if parts else "True"

    # -- values -----------------------------------------------------------
    def value(self, node) -> str:
        kind = node.kind
        if kind == "constant":
            return self.const(node.value)
        if kind == "variable":
            symbol = node.value.data
            pre = self.prebound.get(symbol)
            if pre is not None:
                if pre[1] == "int":
                    return "Int(%s)" % pre[0]      # box the unboxed index
                return pre[0]
            target = self.tmp()
            self.emit("%s = syms.get(%r)" % (target, symbol))
            self.open("if %s is None:" % target)
            self.emit("%s = ctx.get(%r)" % (target, symbol))
            self.close()
            return target
        if kind == "store":
            return self.store(node)
        if kind == "call":
            return self.call(node)
        raise _Uncompilable(kind)

    def store(self, node) -> str:
        if len(node.children) != 1 or node.children[0].kind == "attribute":
            raise _Uncompilable("store")
        value = self.value(node.children[0])
        target = self.tmp()
        self.emit("%s = %s" % (target, value))
        self.open("if %s is not VOID:" % target)
        self.open("if getattr(%s, 'frozen', False) and %s.kind in _CONST_FROZEN:"
                  % (target, target))
        self.emit("%s = _copy_value(%s)" % (target, target))
        self.close()
        self.emit("ctx.set(%r, %s)" % (node.value.data, target))
        self.close()
        return target

    def _modpow(self, node, guards):
        """Rewrite ``mod(pow(b, n), m)`` (also ``inc``/``add`` of a power).

        ``(k + b ** n) % m`` only needs ``b ** n % m``: modular reduction is a
        ring homomorphism, so raising to a power *with* the modulus computes
        the same residue while keeping the intermediate numbers small.  The
        rewrite is guarded on non-negative integers, so it can never change a
        result - it just avoids building gigantic intermediates.
        """
        left = node.children[0]
        addend = 0
        power = left
        if left.kind == "call":
            if left.name == "inc" and len(left.children) == 1:
                addend, power = 1, left.children[0]
            elif left.name == "add" and len(left.children) == 2:
                first, second = left.children
                if first.kind == "constant" and type(first.value) is V.Integer:
                    addend, power = first.value.data, second
                elif second.kind == "constant" and type(second.value) is V.Integer:
                    addend, power = second.value.data, first
        if power.kind != "call" or power.name != "pow" or len(power.children) != 2:
            return None
        if addend < 0:
            return None
        base, exponent = power.children
        if not (_can_fuse(base) and _can_fuse(exponent)):
            return None
        return base, exponent, addend

    def try_modpow(self, node, target) -> bool:
        parts = self._modpow(node, None)
        if parts is None:
            return False
        base, exponent, addend = parts
        modulus = node.children[1]
        if not _can_fuse(modulus):
            return False
        self.leaf_order = []
        self.leaf_locals = {}
        guards: List[str] = []
        # right-to-left evaluation order, like every other argument
        mod_expr = self.fused(modulus, guards)
        base_expr = self.fused(base, guards)
        exp_expr = self.fused(exponent, guards)
        self.emit_leaf_decls()
        reduced = "pow(%s, %s, %s)" % (base_expr, exp_expr, mod_expr)
        if addend:
            reduced = "((%d + %s) %% %s)" % (addend, reduced, mod_expr)
        guards.extend(["%s >= 0" % base_expr, "%s >= 0" % exp_expr,
                       "%s > 0" % mod_expr])
        self.open("if %s:" % self.guard(guards))
        self.emit("%s = Int(%s)" % (target, reduced))
        self.close()
        self.open("else:")
        self.generic_call(node, target)
        self.close()
        return True

    def condition(self, node) -> str:
        """Emit ``node`` so that its truth value is a plain Python bool."""
        if (node.kind == "constant" and type(node.value) is V.Block
                and self.trees is not None):
            # a block condition is *evaluated*, not tested as a value
            inner = self.trees(node.value)
            if len(inner.children) == 1:
                return self.condition(inner.children[0])
            raise _Uncompilable("block condition")
        if (node.kind == "call" and node.name in _CMP_OPS and len(node.children) == 2
                and _can_fuse(node.children[0]) and _can_fuse(node.children[1])):
            self.leaf_order = []
            self.leaf_locals = {}
            guards: List[str] = []
            right = self.fused(node.children[1], guards)
            left = self.fused(node.children[0], guards)
            self.emit_leaf_decls()
            result = self.tmp()
            self.open("if %s:" % self.guard(guards))
            self.emit("%s = %s %s %s" % (result, left, _CMP_OPS[node.name], right))
            self.close()
            self.open("else:")
            value = self.value(node)
            self.emit("%s = _is_true(%s)" % (result, value))
            self.close()
            return result
        value = self.value(node)
        result = self.tmp()
        self.emit("%s = _is_true(%s)" % (result, value))
        return result

    def statement(self, node) -> str:
        """Compile one statement of an inlined block; returns its value."""
        if node.kind == "call":
            name = node.name
            if name in _SLOW_CALLS and name not in _COMPILABLE_SLOW:
                self.control(name, node)
                return ""
            if name == "if":
                target = self.try_inline_if(node)
                if target is not None:
                    return target
        return self.value(node)

    def control(self, name: str, node) -> None:
        """Compile ``return``/``break``/``continue`` into the matching signal."""
        if name == "return":
            if node.children:
                self.emit("raise _ReturnSignal(%s)" % self.value(node.children[0]))
            else:
                self.emit("raise _ReturnSignal(NULL)")
        elif name == "break":
            self.emit("raise _BreakSignal()")
        elif name == "continue":
            self.emit("raise _ContinueSignal()")
        else:
            raise _Uncompilable(name)

    def try_inline_if(self, node):
        """Inline ``if condition -> body`` (a straight jump, no dispatch)."""
        children = node.children
        if len(children) != 2 or self.trees is None:
            return None
        body = children[1]
        if body.kind != "constant" or type(body.value) is not V.Block:
            return None
        try:
            tree = self.trees(body.value)
            save_lines, save_depth = self.lines, self.depth
            self.lines = []
            self.depth = 0
            try:
                values = [self.statement(stmt) for stmt in tree.children]
            except _Uncompilable:
                self.lines = save_lines
                self.depth = save_depth
                return None
            inner, self.lines = self.lines, save_lines
            self.depth = save_depth
        except _Uncompilable:
            return None
        try:
            test = self.condition(children[0])
        except _Uncompilable:
            return None
        target = self.tmp()
        self.emit("%s = VOID" % target)
        self.open("if %s:" % test)
        pad = "    " * self.depth
        self.lines.extend(pad + line for line in inner)
        if values and values[-1]:
            self.emit("%s = %s" % (target, values[-1]))
        self.close()
        return target

    def try_convert(self, node, target) -> bool:
        """``to :integer`` / ``to :string`` without a builtin lookup."""
        children = node.children
        if len(children) != 2 or children[0].kind != "constant":
            return False
        kind = children[0].value
        if type(kind) is not V.Type:
            return False
        helper = _CONVERT_FAST.get(kind.data)
        if helper is None:
            return False
        for child in children:
            if child.kind == "attribute":
                return False
        value = self.value(children[1])
        raw = self.tmp()
        self.emit("%s = %s(ev, %s)" % (raw, helper[0], value))
        self.open("if %s is None:" % raw)
        self.generic_call(node, target)
        self.close()
        self.open("else:")
        self.emit("%s = %s(%s)" % (target, helper[1], raw))
        self.close()
        return True

    def call(self, node) -> str:
        children = node.children
        name = node.name
        if name == "if":
            target = self.try_inline_if(node)
            if target is not None:
                return target
        if name in _SLOW_CALLS and name not in _COMPILABLE_SLOW:
            raise _Uncompilable(name)
        target = self.tmp()
        for child in children:
            if child.kind == "attribute":
                # attributes reach the builtin through the attribute stack, so
                # a call that has any is never fused - only dispatched
                self.generic_call(node, target)
                return target
        if name == "to" and self.try_convert(node, target):
            return target
        if name == "mod" and len(children) == 2:
            if self.try_modpow(node, target):
                return target
        if name in _CMP_OPS and len(children) == 2 and \
                _can_fuse(children[0]) and _can_fuse(children[1]):
            self.leaf_order = []
            self.leaf_locals = {}
            guards: List[str] = []
            # arguments are evaluated right-to-left, so are the leaves
            right = self.fused(children[1], guards)
            left = self.fused(children[0], guards)
            expr = "(%s %s %s)" % (left, _CMP_OPS[name], right)
            self.emit_leaf_decls()
            self.open("if %s:" % self.guard(guards))
            self.emit("%s = TRUE if %s else FALSE" % (target, expr))
            self.close()
            self.open("else:")
            self.generic_call(node, target)
            self.close()
            return target
        if name in _INT_OPS and len(children) == 2 and _can_fuse(node):
            self.leaf_order = []
            self.leaf_locals = {}
            guards = []
            expr = self.fused(node, guards)
            self.emit_leaf_decls()
            self.open("if %s:" % self.guard(guards))
            self.emit("%s = Int(%s)" % (target, expr))
            self.close()
            self.open("else:")
            self.generic_call(node, target)
            self.close()
            return target
        self.generic_call(node, target)
        return target

    def attribute(self, node) -> None:
        """Push ``.attr:value`` onto the attribute stack."""
        self.emit("ctx.push_attr(%r, %s)"
                  % (node.value.data, self.value(node.children[0])))

    def generic_call(self, node, target) -> None:
        name = node.name
        ref = "%s, %r" % (self.node_ref(node), name)
        args = []
        has_attr = False
        for child in reversed(node.children):
            if child.kind == "attribute":
                has_attr = True
                self.attribute(child)
                continue
            args.append(self.value(child))
        if not args:
            self.emit("%s = _dispatch(ev, %s, [])" % (target, ref))
            return
        if len(args) == 1:
            self.emit("%s = _dispatch(ev, %s, [] if %s is VOID else [%s])"
                      % (target, ref, args[0], args[0]))
            return
        # ``args`` is in evaluation (right-to-left) order; ``ordered`` is in
        # declaration order, which is what every call ultimately receives.
        first, second = args[0], args[1]
        ordered = args[::-1]
        self.open("if %s is VOID or %s is VOID:" % (first, second))
        self.emit("%s = _dispatch(ev, %s, _order_args(%s))"
                  % (target, ref, ", ".join(args)))
        self.close()
        if len(args) == 2 and name in _INT_SPEC and not has_attr:
            left, right = ordered[0], ordered[1]
            self.open("elif type(%s) is Int and type(%s) is Int:" % (left, right))
            lhs = "%s.data" % left
            rhs = "%s.data" % right
            if name in _INT_OPS:
                self.emit("%s = Int(%s %s %s)" % (target, lhs, _INT_OPS[name], rhs))
            elif name in _CMP_OPS:
                self.emit("%s = TRUE if %s %s %s else FALSE"
                          % (target, lhs, _CMP_OPS[name], rhs))
            else:
                # the helper signals "not applicable" by returning None, so
                # keep its result instead of calling it twice (that doubles
                # the cost of e.g. big-integer exponentiation)
                helper = _HELPER_OPS[name]
                raw = self.tmp()
                self.emit("%s = %s(%s, %s)" % (raw, helper, lhs, rhs))
                self.open("if %s is None:" % raw)
                self.emit("%s = _dispatch(ev, %s, [%s, %s])"
                          % (target, ref, left, right))
                self.close()
                self.open("else:")
                self.emit("%s = Int(%s)" % (target, raw))
                self.close()
            self.close()
        self.open("else:")
        self.emit("%s = _dispatch(ev, %s, [%s])"
                  % (target, ref, ", ".join(ordered)))
        self.close()


def _to_int_fast(ev, value):
    """``to :integer`` for the common cases (``None`` => use the builtin)."""
    if ev.ctx.attrs:
        return None
    kind = value.kind
    if kind == "integer":
        return value.data
    if kind == "string":
        text = value.data
        if text.isdigit():
            return int(text) if len(text) < 19 else None
        text = text.strip()
        if len(text) > 15:
            return None
        try:
            if text[:2].lower() == "0x":
                return int(text, 16)
            if "." in text or "e" in text.lower():
                return int(float(text))
            return int(text)
        except ValueError:
            return None
    return None


def _to_str_fast(ev, value):
    """``to :string`` for the common cases (``None`` => use the builtin)."""
    if ev.ctx.attrs:
        return None
    kind = value.kind
    if kind == "string":
        return value.data
    if kind == "integer":
        return str(value.data)
    if kind == "char":
        return value.data
    return None


_CONVERT_FAST = {"integer": ("_to_int_fast", "Int"),
                 "string": ("_to_str_fast", "String")}


def _break_signal():
    from .evaluator import BreakSignal
    return BreakSignal


def _continue_signal():
    from .evaluator import ContinueSignal
    return ContinueSignal


def _return_signal():
    from .evaluator import ReturnSignal
    return ReturnSignal


_BreakSignal = _break_signal()
_ContinueSignal = _continue_signal()
_ReturnSignal = _return_signal()

_UNCACHED = object()


def _fully_fused(node) -> bool:
    if node.kind == "call" and node.name in _CMP_OPS and len(node.children) == 2:
        return _can_fuse(node.children[0]) and _can_fuse(node.children[1])
    return _can_fuse(node)


# guard snippets for leaves whose type is a union
_TYPE_TEST = {
    "Seq": "(type({0}) is Block or type({0}) is String or type({0}) is Inline)",
}

_PURE_CALLS = frozenset(_INT_OPS) | frozenset(_CMP_OPS) | frozenset(_UNARY_OPS) \
    | frozenset(_HELPER_OPS)


def _pure(node, trees=None) -> bool:
    """Can this statement run without observing or mutating the symbol table?

    Such statements only combine values that are read once, so their free
    variables may be hoisted out of the loop.  Blocks, stores and any other
    call (a user function could touch globals, or evaluate a closure that
    rebinds the loop parameter) disqualify a statement.
    """
    kind = node.kind
    if kind == "constant":
        return type(node.value) is not V.Block and type(node.value) is not V.Inline
    if kind == "variable":
        return True
    if kind != "call":
        return False
    name = node.name
    children = node.children
    if name == "if":
        if not children or not _pure(children[0], trees):
            return False
        body = children[1] if len(children) > 1 else None
        if body is None:
            return True
        if body.kind == "constant" and type(body.value) is V.Block:
            if trees is None:
                return False
            try:
                inner = trees(body.value)
            except Exception:  # pragma: no cover - defensive
                return False
            return all(_pure(stmt, trees) for stmt in inner.children)
        return False
    if name in ("return", "break", "continue"):
        return all(_pure(child, trees) for child in children)
    if name not in _PURE_CALLS and name != "get":
        return False
    return all(_pure(child, trees) for child in children)


def _has_control_flow(node) -> bool:
    """Does the subtree contain ``break``/``continue``/``return``?"""
    if node.kind == "call" and node.name in _SLOW_CALLS \
            and node.name not in _COMPILABLE_SLOW:
        return True
    for child in node.children:
        if _has_control_flow(child):
            return True
    return False


def _loop_limit() -> None:
    from .evaluator import ArturoError

    raise ArturoError("Value Error", "loop limit exceeded")


def _codegen_while(cond_nodes, body_nodes, until: bool, trees=None):
    """Compile a whole ``while``/``until`` statement into one function."""
    if not cond_nodes or not body_nodes:
        return None
    compiler = _Compiler(trees=trees)
    try:
        compiler.depth = 2
        if len(cond_nodes) == 1:
            test = compiler.condition(cond_nodes[0])
        else:
            for node in cond_nodes[:-1]:
                compiler.statement(node)
            test = compiler.condition(cond_nodes[-1])
        cond_lines = compiler.lines

        compiler.lines = []
        compiler.depth = 3
        values = [compiler.statement(node) for node in body_nodes]
        body_lines = compiler.lines
    except _Uncompilable:
        return None
    tail = []
    if values and values[-1]:
        tail.append("            last = %s" % values[-1])
    guard = ("        if %s: break" if until else "        if not %s: break") % test
    body_run = (
        "        n += 1\n"
        "        if n > 5000000:\n"
        "            _loop_limit()\n"
        "        try:\n"
        + "\n".join(body_lines) + "\n"
        + ("\n".join(tail) + "\n" if tail else "")
        + "        except _BreakSignal:\n"
        "            break\n"
        "        except _ContinueSignal:\n"
        + ("            pass\n" if until else "            continue\n")
    )
    head = (
        "def _loop(ev, _c=_c, _n=_n):\n"
        "    ctx = ev.ctx\n"
        "    syms = ctx.syms\n"
        "    last = NULL\n"
        "    n = 0\n"
        "    while True:\n"
    )
    if until:
        source = head + body_run + "\n".join(cond_lines) + "\n" + guard + "\n    return last\n"
    else:
        source = head + "\n".join(cond_lines) + "\n" + guard + "\n" + body_run \
            + "    return last\n"
    namespace = _namespace(compiler)
    try:
        exec(compile(source, "<arturo-fastloop>", "exec"), namespace)
    except SyntaxError:  # pragma: no cover - defensive
        return None
    return namespace["_loop"]


def while_plan(cond_tree, body_tree, until: bool, trees=None):
    """Cached compiled ``while``/``until`` for these two block trees."""
    if cond_tree is None or body_tree is None:
        return None
    meta = cond_tree.meta
    if meta is None:
        meta = cond_tree.meta = {}
    key = ("while", id(body_tree), until)
    plan = meta.get(key, _UNCACHED)
    if plan is _UNCACHED:
        plan = _codegen_while(cond_tree.children, body_tree.children, until, trees)
        meta[key] = plan
    return plan


def _namespace(compiler) -> dict:
    """Globals shared by every generated function."""
    return {
        "Int": V.Integer, "String": V.String, "Block": V.Block,
        "Inline": V.Inline,
        "TRUE": V.TRUE, "FALSE": V.FALSE, "VOID": V.VOID, "NULL": V.NULL,
        "_dispatch": _dispatch, "_order_args": _order_args,
        "_int_div": _int_div, "_int_mod": _int_mod, "_int_pow": _int_pow,
        "_copy_value": V.copy_value, "_CONST_FROZEN": _CONST_FROZEN,
        "_is_true": V.is_true, "_BreakSignal": _BreakSignal,
        "_ContinueSignal": _ContinueSignal, "_ReturnSignal": _ReturnSignal,
        "_to_int_fast": _to_int_fast, "_to_str_fast": _to_str_fast,
        "_loop_limit": _loop_limit,
        "_c": tuple(compiler.consts), "_n": compiler.nodes,
    }


def _codegen_iterator(nodes, mode: str, param: str, wrap_int: bool,
                      index_name: str = None, trees=None):
    """Compile a whole ``select``/``map``/``filter``/``loop`` into one function.

    The generic loop pays a Python call, a boxing operation and a truth test
    per item.  This emits the loop, the parameter binding and the statements as
    one straight-line function, so numeric predicates never build an
    intermediate value at all.
    """
    if not nodes:
        return None
    for node in nodes:
        if node.kind == "call" and node.name in _SLOW_CALLS \
                and node.name not in _COMPILABLE_SLOW:
            return None
    prebound = {param: ("it", "int" if wrap_int else None)}
    if index_name is not None:
        prebound[index_name] = ("ipos", "int")
    compiler = _Compiler(prebound=prebound, trees=trees)
    compiler.depth = 3
    # hoisting reads the free variables *before* the loop, which is only safe
    # while nothing in the body can write to them
    compiler.hoist = all(_pure(node, trees) for node in nodes)
    try:
        if mode in ("loop", "map"):
            value = ""
            for node in nodes:
                result = compiler.statement(node)
                if result:
                    value = result
            if not value:
                value = "VOID"
            compiler.emit(("last = %s" if mode == "loop" else "append(%s)") % value)
        elif mode in ("every", "some"):
            for node in nodes[:-1]:
                compiler.statement(node)
            test = compiler.condition(nodes[-1])
            compiler.emit(("if %s:" if mode == "some" else "if not %s:") % test)
            compiler.depth += 1
            # plain Python bools: the caller wraps them in a Logical value
            compiler.emit("return %s" % ("True" if mode == "some" else "False"))
            compiler.depth -= 1
        else:
            for node in nodes[:-1]:
                compiler.statement(node)
            test = compiler.condition(nodes[-1])
            compiler.emit(("if %s:" if mode == "select" else "if not %s:") % test)
            compiler.depth += 1
            compiler.emit("append(it)")
            compiler.depth -= 1
    except _Uncompilable:
        return None

    prelude = []
    for local, symbol, expected in compiler.hoisted:
        if symbol is None:
            continue
        prelude.append("    %s = syms.get(%r)" % (local, symbol))
        prelude.append("    if %s is None:" % local)
        prelude.append("        %s = ctx.get(%r)" % (local, symbol))
        prelude.append("    ok_%s = type(%s) is %s" % (local, local, expected))
    bind = ["        it = raw"]
    if index_name is not None:
        bind.append("        ipos = pos")
        bind.append("        pos += 1")
        if not compiler.hoist:
            bind.append("        syms[%r] = Int(ipos)" % index_name)
    if not compiler.hoist:
        bind.append("        syms[%r] = %s" % (param, "Int(it)" if wrap_int else "it"))
    body = "\n".join(compiler.lines)
    source = (
        "def _iter(ev, seq, _c=_c, _n=_n):\n"
        "    ctx = ev.ctx\n"
        "    syms = ctx.syms\n"
        + ("    last = NULL\n" if mode == "loop" else
           "" if mode in ("every", "some") else
           "    out = []\n    append = out.append\n")
        + ("    pos = 0\n" if index_name is not None else "")
        + "\n".join(prelude) + ("\n" if prelude else "")
        + "    for raw in seq:\n"
        + "\n".join(bind) + "\n"
        "        try:\n"
        + body + "\n"
        "        except _BreakSignal:\n"
        "            break\n"
        "        except _ContinueSignal:\n"
        "            continue\n"
        + ("    return last\n" if mode == "loop" else
           "    return %s\n" % ("True" if mode == "every" else "False")
           if mode in ("every", "some") else
           ("    return [Int(v) for v in out]\n"
            if wrap_int and mode in ("select", "filter") else "    return out\n"))
    )
    namespace = _namespace(compiler)
    try:
        exec(compile(source, "<arturo-fastloop>", "exec"), namespace)
    except SyntaxError:  # pragma: no cover - defensive
        return None
    return namespace["_iter"]


def iterator_plan(tree: Node, mode: str, param: str, wrap_int: bool,
                  index_name: str = None, trees=None):
    """Cached compiled loop for ``tree``, or ``None`` when unavailable."""
    meta = tree.meta
    if meta is None:
        meta = tree.meta = {}
    key = (mode, param, wrap_int, index_name)
    plan = meta.get(key, _UNCACHED)
    if plan is _UNCACHED:
        plan = _codegen_iterator(tree.children, mode, param, wrap_int,
                                 index_name, trees) if tree.children else None
        meta[key] = plan
    return plan


def _codegen(node):
    """Compile ``node`` into a Python function, or return ``None``."""
    if node.kind not in ("call", "store", "variable"):
        return None
    if _call_count(node) < 2:
        return None
    compiler = _Compiler()
    try:
        result = compiler.value(node)
    except _Uncompilable:
        return None
    except (AttributeError, IndexError):  # pragma: no cover - defensive
        return None
    compiler.emit("return %s" % result)
    source = "def _fast(ev, _c=_c, _n=_n):\n    ctx = ev.ctx\n    syms = ctx.syms\n" \
             + "\n".join(compiler.lines) + "\n"
    namespace = _namespace(compiler)
    try:
        exec(compile(source, "<arturo-fastpath>", "exec"), namespace)
    except SyntaxError:  # pragma: no cover - defensive
        return None
    return namespace["_fast"]


def _order_args(*args):
    """Reproduce the evaluator's argument order for VOID-filtered calls."""
    args = [a for a in args if a is not V.VOID]
    if len(args) > 1:
        args = args[::-1]
    return list(args)


def _compile_node(node) -> None:
    """Attach a compiled closure to simple nodes (no attributes/pipes)."""
    fast = _codegen(node)
    if fast is not None:
        node.fast = fast
        return
    for child in node.children:
        _compile_node(child)
    kind = node.kind
    if kind == "constant":
        value = node.value
        node.fast = lambda ev, _v=value: _v
        return
    if kind == "variable":
        name = node.value.data

        def _var(ev, _name=name):
            value = ev.ctx.syms.get(_name)
            if value is None:
                return ev.ctx.get(_name)
            return value

        node.fast = _var
        return
    if kind == "call":
        if node.name in _SLOW_CALLS:
            return
        parts = []
        for child in node.children:
            if child.fast is None:
                return
            parts.append(child.fast)
        name = node.name

        if len(parts) == 2 and name in _INT_SPEC:
            spec = _INT_SPEC[name]

            def _spec(ev, _p0=parts[0], _p1=parts[1], _spec=spec, _name=name,
                      _node=node):
                if ev.ctx.syms.get(_name) is None:
                    a = _p0(ev)
                    b = _p1(ev)
                    if a is V.VOID or b is V.VOID:
                        return _dispatch(ev, _node, _name,
                                         [x for x in (a, b) if x is not V.VOID])
                    if type(a) is V.Integer and type(b) is V.Integer:
                        x = a.data
                        y = b.data
                        out = _spec(x, y)
                        if out is not None:
                            if out.__class__ is bool:
                                return V.Logical(out)
                            return V.Integer(out)
                    return _dispatch(ev, _node, _name, [a, b])
                return _dispatch(ev, _node, _name, [_p0(ev), _p1(ev)])

            node.fast = _spec
            return

        def _call(ev, _parts=parts, _name=name, _node=node):
            args = [part(ev) for part in reversed(_parts)]
            if any(a is V.VOID for a in args):
                args = [a for a in args if a is not V.VOID]
            if len(args) > 1:
                args.reverse()
            return _dispatch(ev, _node, _name, args)

        node.fast = _call
        return
    if kind == "store":
        if len(node.children) != 1:
            return
        child = node.children[-1]
        if child.fast is None:
            return
        name = node.value.data
        thaw_kinds = ("string", "block", "inline", "dictionary", "object")

        def _store(ev, _child=child.fast, _name=name, _kinds=thaw_kinds):
            value = _child(ev)
            if value is V.VOID:
                return value
            if getattr(value, "frozen", False) and value.kind in _kinds:
                value = V.copy_value(value, deep=False)
            ev.ctx.set(_name, value)
            return value

        node.fast = _store
        return


def build(block: V.Block, library, syms=None) -> Node:
    return AstBuilder(library, syms).build(block)
