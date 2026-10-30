"""
evaluator.py - Arturo's tree-walking evaluator.

Semantics implemented here mirror Arturo's VM:

* nodes are evaluated **post-order** and children are visited in *reverse*
  order (this is why argument side effects happen right-to-left);
* ``call`` nodes resolve a symbol and invoke it with the evaluated children;
* ``attribute`` nodes push on the *attribute stack*, which builtins pop with
  ``ctx.popAttr("name")``;
* blocks are plain values - they only run when something calls
  :meth:`Evaluator.do_block` (``do``, ``if``, iterators, ...);
* user functions get their own scope frame; plain blocks do **not**;
* ``break``/``continue``/``return`` are implemented with signals.

Errors are raised as :class:`ArturoError`, which ``try``/``try?`` turn into
``:error`` values.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import values as V


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
class ArturoError(Exception):
    """A runtime error that `try` can turn into an :error value."""

    def __init__(self, kind: str, message: str, data: Optional[dict] = None):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message
        self.data = data or {}

    def to_value(self) -> V.Error:
        d = {
            "kind": V.String(self.kind),
            "message": V.String(self.message),
        }
        for k, val in self.data.items():
            d[k] = val if isinstance(val, V.Value) else V.String(str(val))
        return V.Error(d)


class ReturnSignal(Exception):
    def __init__(self, value: V.Value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


MISSING = object()


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class Context:
    """Symbol table + attribute stack + scope frames."""

    def __init__(self, library, out=None):
        self.library = library
        self.syms: Dict[str, V.Value] = {}
        self.frames: List[Dict[str, Any]] = []
        self.attrs: List[tuple] = []
        self.out = out
        self.evaluator: Optional["Evaluator"] = None
        self.this_obj: Optional[V.Value] = None
        self.path = ["<script>"]
        self.last_pushed: Optional[V.Value] = None
        self.prev_pushed: Optional[V.Value] = None
        self.error_kind = "Script Error"
        self.trace: List[str] = []
        # stack of value collectors: ``@[ loop ... ]`` gathers every value the
        # enclosed loops push (see ``Evaluator.emit``)
        self.collectors: List[List[V.Value]] = []
        self.emitted = False
        self.depth = 0
        self.cwd = None

    # -- symbols ---------------------------------------------------------
    def get(self, name: str) -> V.Value:
        v = self.syms.get(name, MISSING)
        if v is not MISSING:
            return v
        if name == "this":
            if self.this_obj is not None:
                return self.this_obj
            raise ArturoError("Name Error", "Identifier not found: this")
        fn = self.library.lookup(name)
        if fn is not None:
            return fn
        const = self.library.constant(name)
        if const is not None:
            return const
        raise ArturoError("Name Error", f"Identifier not found: {name}")

    def has(self, name: str) -> bool:
        return (name in self.syms or self.library.lookup(name) is not None
                or self.library.constant(name) is not None)

    def set(self, name: str, value: V.Value) -> None:
        if self.frames:
            frame = self.frames[-1]
            if name not in frame:
                frame[name] = self.syms.get(name, MISSING)
        self.syms[name] = value

    def declare(self, name: str, value: V.Value) -> None:
        self.set(name, value)

    def unset(self, name: str) -> None:
        if name in self.syms:
            del self.syms[name]

    # -- scopes ----------------------------------------------------------
    def push_frame(self, initial: Optional[Dict[str, V.Value]] = None) -> Dict[str, Any]:
        frame: Dict[str, Any] = {}
        self.frames.append(frame)
        if initial:
            for k, v in initial.items():
                self.set(k, v)
        return frame

    def pop_frame(self) -> None:
        frame = self.frames.pop()
        for name, previous in frame.items():
            if previous is MISSING:
                self.syms.pop(name, None)
            else:
                self.syms[name] = previous

    # -- attributes ------------------------------------------------------
    def push_attr(self, name: str, value: V.Value) -> None:
        self.attrs.append((name, value))

    def pop_attr(self, name: str, default=MISSING):
        for i in range(len(self.attrs) - 1, -1, -1):
            if self.attrs[i][0] == name:
                return self.attrs.pop(i)[1]
        return default

    def has_attr(self, name: str) -> bool:
        return any(a[0] == name for a in self.attrs)

    def peek_attr(self, name: str, default=None):
        for i in range(len(self.attrs) - 1, -1, -1):
            if self.attrs[i][0] == name:
                return self.attrs[i][1]
        return default

    def clear_attrs(self) -> List[tuple]:
        a = self.attrs
        self.attrs = []
        return a


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------
class Evaluator:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        ctx.evaluator = self
        self._ast_cache: Dict[int, Any] = {}
        self._ast_lib_version = 0

    # -- public API ------------------------------------------------------
    def eval_node(self, node) -> V.Value:
        kind = node.kind
        if kind == "constant":
            value = node.value
            # Literals in the AST are frozen: every evaluation yields a fresh
            # (shallow) copy, so that in-place mutation cannot leak into the
            # next evaluation.
            if isinstance(value, V.Block):
                return V.Block(list(value.data))
            if isinstance(value, V.Inline):
                return V.Inline(list(value.data))
            if isinstance(value, V.Dictionary):
                return V.Dictionary(dict(value.data))
            return value
        if kind == "variable":
            name = node.value.data
            return self.ctx.get(name)
        if kind == "store":
            value = self._eval_children_first(node)
            if value is V.VOID:
                return value
            self.ctx.set(node.value.data, value)
            return value
        if kind == "attribute":
            value = self._eval_children_first(node)
            self.ctx.push_attr(node.value.data, value)
            return V.NULL
        if kind == "call":
            return self._eval_call(node)
        if kind == "root":
            result: V.Value = V.VOID
            for child in node.children:
                collector = self.ctx.collectors[-1] if self.ctx.collectors else None
                before = len(collector) if collector is not None else 0
                value = self.eval_node(child)
                if value is not V.VOID:
                    result = value
                    self.ctx.last_pushed = value
                    # a statement that only ran a collector-aware block has
                    # already contributed its values
                    if collector is not None and len(collector) == before:
                        collector.append(value)
            return result
        raise ArturoError("VM Error", f"Unknown node kind: {kind}")

    def _eval_children_first(self, node) -> V.Value:
        result: V.Value = V.NULL
        for child in reversed(node.children):
            result = self.eval_node(child)
        return result

    def _eval_call(self, node):
        # `else` needs the value the previous statement pushed
        self.ctx.prev_pushed = self.ctx.last_pushed
        args: List[V.Value] = []
        # children are evaluated right-to-left
        for child in reversed(node.children):
            value = self.eval_node(child)
            if child.kind == "attribute":
                continue
            if value is V.VOID:
                continue
            args.append(value)
        args.reverse()

        fn = self._resolve_callable(node.name)
        result = self.call(fn, args, name=node.name)
        if result is not V.VOID:
            self.ctx.last_pushed = result
        return result

    def _resolve_callable(self, name: str) -> V.Function:
        fn = self.ctx.syms.get(name, MISSING)
        if fn is MISSING:
            fn = self.ctx.library.lookup(name)
        if fn is MISSING or not isinstance(fn, V.Function):
            raise ArturoError("Name Error", f"Identifier not found: {name}")
        return fn

    def _trace_suffix(self) -> str:
        if not self.ctx.trace:
            return ""
        return "\n  in: " + " <- ".join(reversed(self.ctx.trace[-8:]))

    # -- calling ---------------------------------------------------------
    def call(self, fn: V.Function, args: List[V.Value], name: str = "") -> V.Value:
        self.ctx.trace.append(name or fn.name)
        try:
            if fn.is_builtin:
                return self._call_builtin(fn, args)
            return self._call_user(fn, args, name or fn.name)
        finally:
            self.ctx.trace.pop()

    def _call_builtin(self, fn: V.Function, args: List[V.Value]) -> V.Value:
        if len(args) != fn.arity:
            raise ArturoError(
                "Value Error",
                f"Not enough parameters\nCannot perform: {fn.name}"
                + self._trace_suffix(),
            )
        self.ctx.current_fn = fn.name
        self.ctx.depth += 1
        if self.ctx.depth > 2000:
            self.ctx.depth -= 1
            raise ArturoError("Stack Error", "Stack limit exceeded")
        try:
            return fn.impl(self, args)
        except ArturoError:
            raise
        except (BreakSignal, ContinueSignal, ReturnSignal):
            raise
        except RecursionError:
            raise ArturoError("Stack Error", "Stack limit exceeded")
        except ZeroDivisionError:
            raise ArturoError("Arithmetic Error", "Division by zero")
        except ValueError as exc:
            raise ArturoError("Value Error", str(exc))
        finally:
            self.ctx.depth -= 1

    def _call_user(self, fn: V.Function, args: List[V.Value], name: str) -> V.Value:
        if len(args) != fn.arity:
            raise ArturoError(
                "Value Error",
                f"Not enough parameters\nCannot perform: {name}",
            )
        if fn.memoize:
            key = tuple(V.value_key(a) for a in args)
            if not hasattr(fn, "_memo"):
                fn._memo = {}
            if len(fn._memo) > 200_000:
                fn._memo.clear()
            if key in fn._memo:
                return fn._memo[key]

        self.ctx.depth += 1
        if self.ctx.depth > 12000:
            self.ctx.depth -= 1
            raise ArturoError("Stack Error", "Stack limit exceeded")

        params = [p for p in fn.params if not isinstance(p, V.Type)]
        scoped = not fn.inline
        if scoped:
            self.ctx.push_frame()
        else:
            self.ctx.push_frame()

        prev_this = self.ctx.this_obj
        try:
            for param, arg in zip(params, args):
                self.ctx.set(param_name(param), arg)
            try:
                result = self.do_block(fn.body, scoped=False)
            except ReturnSignal as ret:
                result = ret.value
        finally:
            self.ctx.this_obj = prev_this
            self.ctx.pop_frame()
            self.ctx.depth -= 1

        if fn.memoize:
            fn._memo[key] = result
        return result

    # -- blocks ----------------------------------------------------------
    # -- value collection (for ``@[ ... ]``) -----------------------------
    def emit(self, value: V.Value) -> None:
        """Push a value into the active collector (inline block or none)."""
        if self.ctx.collectors:
            self.ctx.collectors[-1].append(value)

    def collect_block(self, block: V.Block) -> List[V.Value]:
        items: List[V.Value] = []
        self.ctx.collectors.append(items)
        try:
            self.do_block(block)
        finally:
            self.ctx.collectors.pop()
        return items

    def do_block(self, block: V.Value, scoped: bool = False) -> V.Value:
        """Evaluate a block (or inline) in the current scope."""
        if not isinstance(block, V.Block):
            if block is None:
                return V.NULL
            return block
        tree = self._tree_for(block)
        if scoped:
            self.ctx.push_frame()
            try:
                return self.eval_node(tree)
            finally:
                self.ctx.pop_frame()
        return self.eval_node(tree)

    def do_block_scoped(self, block: V.Value) -> V.Value:
        """Evaluate a block with a fresh scope (used by `function.inline` etc.)"""
        return self.do_block(block, scoped=True)

    def _tree_for(self, block: V.Block):
        from . import ast as A

        key = id(block)
        cached = self._ast_cache.get(key)
        if cached is not None and cached[0] == len(block.data) and cached[1] is block.data:
            return cached[2]
        tree = A.build(block, self.ctx.library, self.ctx.syms)
        self._ast_cache[key] = (len(block.data), block.data, tree)
        return tree

    # -- helpers for builtins -------------------------------------------
    def eval_value(self, v: V.Value) -> V.Value:
        """Evaluate a single value (block => run it, other => itself)."""
        if isinstance(v, V.Block):
            return self.do_block(v)
        return v

    def inplace_target(self, arg: V.Value):
        """Resolve a Literal/PathLiteral to (getter, setter) for in-place ops."""
        ctx = self.ctx
        if isinstance(arg, V.Literal):
            name = arg.data
            return (lambda: ctx.get(name), lambda v: ctx.set(name, v))
        if isinstance(arg, V.PathLiteral):
            parts = arg.data
            root = parts[0].data
            base = lambda: ctx.get(root)

            def getter():
                cur = ctx.get(root)
                for key in parts[1:]:
                    cur = _get_path(self, cur, key)
                return cur

            def setter(value):
                if len(parts) == 1:
                    ctx.set(root, value)
                    return
                container = ctx.get(root)
                for key in parts[1:-1]:
                    container = _get_path(self, container, key)
                _set_path(self, container, parts[-1], value)

            return getter, setter
        raise ArturoError("Value Error", "Given value is not a literal")


def param_name(param: V.Value) -> str:
    if isinstance(param, V.Word):
        return param.data
    if isinstance(param, V.Literal):
        return param.data
    return str(param)


def _get_path(ev: "Evaluator", container: V.Value, key: V.Value) -> V.Value:
    from . import builtins_collections as BC

    return BC.get_value(ev, container, key)


def _set_path(ev: "Evaluator", container: V.Value, key: V.Value, value: V.Value) -> None:
    from . import builtins_collections as BC

    BC.set_value(ev, container, key, value)
