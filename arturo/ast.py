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
from .parser import INFIX_ALIASES, PREFIX_ALIASES, STRUCTURAL

# infix aliases registered at runtime via ``alias.infix``
DYNAMIC_INFIX: dict = {}


class Node:
    """A node of the generated tree."""

    __slots__ = ("kind", "children", "parent", "params", "arity", "value", "name",
                 "cache", "fast")

    def __init__(self, kind: str, arity: int = -1, value=None, name: str = ""):
        self.kind = kind
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self.params = 0
        self.cache = None
        self.fast = None
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


def _compile_node(node) -> None:
    """Attach a compiled closure to simple nodes (no attributes/pipes)."""
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

        def _call(ev, _parts=parts, _name=name, _node=node):
            ctx = ev.ctx
            fn = ctx.syms.get(_name)
            if fn is None or not isinstance(fn, V.Function):
                fn = _node.cache
                if fn is None:
                    fn = ev._resolve_callable(_name)
                    _node.cache = fn
            args = [part(ev) for part in _parts]
            impl = fn.impl
            if impl is not None:
                result = impl(ev, args)
            else:
                result = ev._call_user(fn, args, _name)
            if result is not V.VOID:
                ctx.last_pushed = result
            return result

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
