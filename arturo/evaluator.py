"""
evaluator.py - Walks the AST produced by :mod:`arturo.parser`.

Each AST node carries its own :meth:`eval` step.  A :class:`Context` keeps the
current scope and library.

Notable Arturo features supported:
* right-to-left evaluation of infix expressions
* dynamic function-table (so user-defined functions are called as
  functions, not loaded as variables)
* ``switch`` with multi-branch ``switch cond [then] [else]``
* ``break`` / ``continue`` / ``return``
* ``define :type [...]`` and ``to :type [...]`` (custom types)
* path assignment (``a\\b: v``)
* ``this`` keyword inside methods
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from . import parser as P
from . import values as V


class ReturnSignal(Exception):
    def __init__(self, value: V.Value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class Context:
    def __init__(self, library, scope=None, stack=None):
        self.library = library
        self.scope: Dict[str, V.Value] = scope if scope is not None else {}
        self.stack: List[V.Value] = stack if stack is not None else []
        # Current `this` object (for methods)
        self.this_obj: Optional[V.Value] = None

    def get(self, name: str) -> V.Value:
        v = self.scope.get(name)
        if v is None:
            if name == "pi":
                return V.Floating(3.141592653589793)
            if name == "epsilon":
                return V.Floating(2.718281828459045)
            if name == "true":
                return V.Logical(True)
            if name == "false":
                return V.Logical(False)
            if name == "maybe":
                return V.Logical("maybe")
            if name == "null":
                return V.Null()
            if name == "this":
                return self.this_obj if self.this_obj is not None else V.Null()
            fn = self.library.lookup(name)
            if fn is not None:
                return fn
            return V.Null()
        return v

    def set(self, name: str, value: V.Value) -> None:
        self.scope[name] = value


# ---------------------------------------------------------------------------
# Symbol -> function name mapping for infix aliases
# ---------------------------------------------------------------------------
_SYMBOL_TO_FUNC = {
    "+": "add", "++": "append", "-": "sub", "--": "remove",
    "*": "mul", "**": "pow", "/": "div", "//": "fdiv",
    "/%": "divmod", "%": "mod", "^": "pow",
    "=": "equal?", "==": "equal?", "<>": "notEqual?",
    "<": "less?", "<=": "lessOrEqual?", "=<": "lessOrEqual?",
    ">": "greater?", ">=": "greaterOrEqual?",
    "..": "range", "...": "range3",
    "&": "and?", "∧": "and?", "|": "or?", "∨": "or?",
    "?": "switch", "@": "array", "#": "dictionary",
    "!!": "doubleNegation", "~": "render",
    "!": "not?",
}


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------
class Evaluator:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    # -- top level --------------------------------------------------------
    def exec_program(self, stmts: List[object]) -> Optional[V.Value]:
        last: Optional[V.Value] = None
        i = 0
        while i < len(stmts):
            s = stmts[i]
            try:
                if isinstance(s, P.SExpr):
                    last = self.eval_expr(s.expr)
                elif isinstance(s, P.SAssign):
                    val = self.eval_expr(s.value)
                    self.ctx.set(s.name, val)
                    last = val
                elif isinstance(s, P.SPathAssign):
                    val = self.eval_expr(s.value)
                    self._set_path(s.path, val)
                    last = val
                elif isinstance(s, P.SReturn):
                    raise ReturnSignal(self.eval_expr(s.value))
                elif isinstance(s, P.SIf):
                    cond = self._reduce(s.cond)
                    if V.truthy(cond):
                        last = self._exec_branch(s.then_branch)
                    elif s.else_branch is not None:
                        last = self._exec_branch(s.else_branch)
                elif isinstance(s, P.SWhile):
                    last = self._exec_while(s.cond, s.body)
                elif isinstance(s, tuple) and s and s[0] == "loop":
                    last = self._exec_loop(s[1])
                elif isinstance(s, P.SBreak):
                    raise BreakSignal()
                elif isinstance(s, P.SContinue):
                    raise ContinueSignal()
                elif isinstance(s, P.SEmpty):
                    pass
                else:
                    last = self.eval_expr(s)
            except BreakSignal:
                # propagate up out of loops
                raise
            except ContinueSignal:
                # if we're inside a loop, swallow; otherwise re-raise
                # (we don't track nesting explicitly; assume caller is loop)
                raise
            i += 1
        return last

    # -- expression eval --------------------------------------------------
    def eval_expr(self, node) -> V.Value:
        if isinstance(node, P.EValue):
            return node.value
        if isinstance(node, P.EVar):
            return self.ctx.get(node.name)
        if isinstance(node, P.ELiteral):
            # ``'foo`` evaluates to the variable named foo
            return self.ctx.get(node.name)
        if isinstance(node, P.EPathLiteral):
            return self._get_path_literal(node)
        if isinstance(node, P.EPath):
            return self._get_path(node)
        if isinstance(node, P.ESym):
            return self._eval_sym(node)
        if isinstance(node, P.ECall):
            return self._eval_call(node)
        if isinstance(node, P.EBlock):
            # Use the LAST item's value (like ``while [cond]``).
            if not node.items:
                return V.Null()
            last = V.Null()
            for it in node.items:
                if isinstance(it, V.Value):
                    last = it
                else:
                    last = self.eval_expr(it)
            return last
        if isinstance(node, P.EInline):
            if not node.items:
                return V.Null()
            last = V.Null()
            for it in node.items:
                if isinstance(it, V.Value):
                    last = it
                else:
                    last = self.eval_expr(it)
            return last
        if isinstance(node, P.EArrow):
            return self.eval_expr(node.body)
        if isinstance(node, P.EFatArrow):
            target = self.eval_expr(node.target)
            return self._fat_arrow(target)
        if isinstance(node, P.EColon):
            items = [self.eval_expr(c) for c in node.items]
            return V.Block(items)
        if isinstance(node, P.SAssign):
            # Bare label as expression (rare): just null
            return V.Null()
        raise RuntimeError(f"Unknown AST node: {node!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _reduce(self, node) -> V.Value:
        if isinstance(node, P.EBlock):
            if not node.items:
                return V.Null()
            last = V.Null()
            for it in node.items:
                if isinstance(it, V.Value):
                    last = it
                else:
                    last = self.eval_expr(it)
            return last
        return self.eval_expr(node)

    def _exec_branch(self, branch) -> Optional[V.Value]:
        if isinstance(branch, P.EBlock):
            last: Optional[V.Value] = None
            for item in branch.items:
                last = self.eval_expr(item)
            return last
        if isinstance(branch, P.EArrow):
            return self.eval_expr(branch.body)
        if isinstance(branch, tuple) and branch and branch[0] == "loop":
            return self._exec_loop(branch[1])
        return self.eval_expr(branch)

    def _exec_while(self, cond, body) -> V.Value:
        last = V.Null()
        while True:
            try:
                cond_v = self._reduce(cond)
                if not V.truthy(cond_v):
                    break
                last = self._exec_branch(body_ast)
            except ContinueSignal:
                continue
            except BreakSignal:
                break
        return last

    def _exec_loop(self, expr) -> V.Value:
        """``loop collection 'var body`` — expr is an ECall to ``loop``."""
        from .stdlib import _iter as _std_iter
        if not isinstance(expr, P.ECall):
            return V.Null()
        # Do NOT pre-evaluate all args.  Evaluate only the collection;
        # the body and binding literal must remain as AST nodes.
        coll = self.eval_expr(expr.args[0])
        # Literal bind name (if any)
        bind_name: Optional[str] = None
        body_ast = None
        if len(expr.args) >= 2:
            if isinstance(expr.args[1], P.EValue) and isinstance(expr.args[1].value, V.VLiteral):
                bind_name = expr.args[1].value.name
                if len(expr.args) >= 3:
                    body_ast = expr.args[2]
            else:
                body_ast = expr.args[1]
        if body_ast is None:
            return V.Null()
        last = V.Null()
        for item in _std_iter(coll):
            saved = self.ctx.scope.get(bind_name) if bind_name else None
            if bind_name:
                self.ctx.scope[bind_name] = item
            try:
                last = self._exec_branch(body_ast)
            except ContinueSignal:
                continue
            except BreakSignal:
                break
            finally:
                if bind_name is not None:
                    if saved is not None:
                        self.ctx.scope[bind_name] = saved
                    else:
                        self.ctx.scope.pop(bind_name, None)
        return last

    def _eval_sym(self, node: P.ESym) -> V.Value:
        sym_to_func = _SYMBOL_TO_FUNC
        fname = sym_to_func.get(node.op, node.op)
        fn = self.ctx.library.lookup(fname)
        if fn is None:
            # Try bitwise operators and other specialised names
            fn = self.ctx.library.lookup(node.op)
        if fn is None:
            raise RuntimeError(f"Unknown infix operator: {node.op!r}")
        if node.left is None:
            arg = self.eval_expr(node.right)
            return fn.impl(self.ctx, [arg])
        left = self.eval_expr(node.left)
        right = self.eval_expr(node.right)
        return fn.impl(self.ctx, [left, right])

    def _eval_call(self, node: P.ECall) -> V.Value:
        # Special forms
        if isinstance(node.func, P.EVar):
            if node.func.name == "__build_function__":
                return self._build_function(node.args)
            if node.func.name == "__build_type__":
                return self._build_type(node.args)
            # ``map``/``select``/``filter``/``do`` -- keep AST nodes for args
            # that are blocks so the body is evaluated per-iteration.
            if node.func.name in ("map", "select", "filter", "do"):
                fn = self.ctx.library.lookup(node.func.name)
                return self._call_higher_order(fn, node.args)
        func = self.eval_expr(node.func) if isinstance(node.func, P.EVar) else node.func
        args = [self.eval_expr(a) for a in node.args]
        if isinstance(func, V.VBuiltinFunction):
            return func.impl(self.ctx, args)
        if isinstance(func, V.VFunction):
            return self._call_user_function(func, args)
        if isinstance(func, V.VObject):
            # Object call - treat as method call on self
            # But normally methods are accessed via path
            return V.Null()
        return V.Null()

    def _call_higher_order(self, fn, ast_args: List[object]) -> V.Value:
        """Call map/select/filter/do without pre-evaluating block bodies.

        ``ast_args`` is the raw list of AST nodes; we evaluate only the
        collection and the literal binding name here, and keep the body
        as an AST node for iteration.
        """
        # evaluate the collection
        if not ast_args:
            return V.Null()
        coll = self.eval_expr(ast_args[0])
        # determine binding and body
        bind_name = None
        body_ast = None
        if len(ast_args) >= 2:
            if isinstance(ast_args[1], P.EValue) and isinstance(ast_args[1].value, V.VLiteral):
                bind_name = ast_args[1].value.name
                if len(ast_args) >= 3:
                    body_ast = ast_args[2]
            else:
                body_ast = ast_args[1]
        if body_ast is None:
            return V.Null()
        from .stdlib import _iter as _std_iter
        out: List[V.Value] = []
        for item in _std_iter(coll):
            if bind_name:
                saved = self.ctx.scope.get(bind_name)
                self.ctx.scope[bind_name] = item
            try:
                # ``do`` is special: evaluate the body block as-is
                if fn.name == "do" and isinstance(body_ast, P.EBlock):
                    last = V.Null()
                    for sub in body_ast.items:
                        if isinstance(sub, V.Value):
                            last = self.eval_expr(sub)
                        else:
                            last = self.eval_expr(sub)
                    out.append(last)
                    continue
                # body execution
                if isinstance(body_ast, P.EBlock):
                    last = V.Null()
                    for sub in body_ast.items:
                        if isinstance(sub, V.Value):
                            last = sub
                        else:
                            last = self.eval_expr(sub)
                    res = last
                elif isinstance(body_ast, P.EArrow):
                    res = self.eval_expr(body_ast.body)
                else:
                    res = self.eval_expr(body_ast)
                if fn.name == "map":
                    out.append(res)
                elif fn.name == "select":
                    if V.truthy(res):
                        out.append(item)
                elif fn.name == "filter":
                    if not V.truthy(res):
                        out.append(item)
            finally:
                if bind_name is not None:
                    if saved is not None:
                        self.ctx.scope[bind_name] = saved
                    else:
                        self.ctx.scope.pop(bind_name, None)
        return V.Block(out)

    def _build_function(self, args: List[object]) -> V.VFunction:
        params: List[str] = []
        if args and isinstance(args[0], P.EValue) and isinstance(args[0].value, V.VString):
            params = [p for p in args[0].value.data.split("|") if p]
        body = V.Block(args[1].items) if len(args) > 1 and isinstance(args[1], P.EBlock) else V.Block([])
        return V.Function(params=params, body=body)

    def _build_type(self, args: List[object]) -> V.VObject:
        """Build a custom type prototype object."""
        type_name = ""
        if args and isinstance(args[0], P.EValue) and isinstance(args[0].value, V.VString):
            type_name = args[0].value.data
        # Build a prototype object that holds methods
        proto = V.Object(type_name=type_name)
        if len(args) > 1 and isinstance(args[1], P.EBlock):
            for item in args[1].items:
                if isinstance(item, P.SAssign):
                    # ``init: method [...]`` or ``init: constructor [...]``
                    method_body = item.value
                    # Wrap into a function.  Use method/constructor markers.
                    if isinstance(method_body, P.ECall) and isinstance(method_body.func, P.EVar):
                        if method_body.func.name in ("method", "constructor"):
                            # method [...]: a function with implicit `this`
                            params = []
                            if method_body.args and isinstance(method_body.args[0], P.EBlock):
                                params = [p.name for p in method_body.args[0].items if isinstance(p, V.VWord)]
                            body_block = method_body.args[1] if len(method_body.args) > 1 else None
                            if isinstance(body_block, P.EBlock):
                                fn = V.Function(params=params, body=V.Block(body_block.items))
                                proto.fields[item.name] = fn
                            elif isinstance(body_block, P.EArrow):
                                fn = V.Function(params=params, body=V.Block([body_block.body]))
                                proto.fields[item.name] = fn
                    else:
                        # plain method: ``methodName: <block or arrow>``
                        method_body = item.value
                        params = []
                        if isinstance(method_body, P.EBlock):
                            params = [p.name for p in method_body.items if isinstance(p, V.VWord)]
                            fn = V.Function(params=params, body=method_body)
                            proto.fields[item.name] = fn
                        elif isinstance(method_body, P.EArrow):
                            fn = V.Function(params=params, body=V.Block([method_body.body]))
                            proto.fields[item.name] = fn
        # Register the prototype so ``to :type args`` can find it
        self.ctx.library.register_type(type_name, proto)
        return proto

    def _call_user_function(self, func: V.VFunction, args: List[V.Value]) -> V.Value:
        old_scope = self.ctx.scope
        old_this = self.ctx.this_obj
        new_scope = dict(old_scope)  # inherit parent scope
        for i, p in enumerate(func.params):
            if i < len(args):
                new_scope[p] = args[i]
            else:
                new_scope[p] = V.Null()
        self.ctx.scope = new_scope
        try:
            ev = Evaluator(self.ctx)
            if not isinstance(func.body, V.VBlock):
                return V.Null()
            stmts: List[object] = []
            for item in func.body.items:
                if isinstance(item, V.Value):
                    stmts.append(P.SExpr(P.EValue(item)))
                elif isinstance(item, (P.SExpr, P.SAssign, P.SIf, P.SWhile, P.SReturn, P.SBreak, P.SContinue)):
                    stmts.append(item)
                else:
                    stmts.append(P.SExpr(item))
            try:
                last = ev.exec_program(stmts)
            except ReturnSignal as ret:
                return ret.value
            return last if last is not None else V.Null()
        finally:
            self.ctx.scope = old_scope
            self.ctx.this_obj = old_this

    def _fat_arrow(self, target) -> V.VFunction:
        if isinstance(target, V.VBuiltinFunction):
            arity = max(target.arity, 0)
        elif isinstance(target, V.VFunction):
            arity = len(target.params)
        else:
            arity = 1
        params = [f"__a{i}__" for i in range(arity)]
        body_items: List[V.Value] = []
        body_items.append(V.Word(target.name if isinstance(target, V.VBuiltinFunction) else "do"))
        for i in range(arity):
            body_items.append(V.Word(params[i]))
        return V.Function(params=params, body=V.Block(body_items))

    # ------------------------------------------------------------------
    # Path support
    # ------------------------------------------------------------------
    def _get_path(self, node: P.EPath) -> V.Value:
        root = self.eval_expr(node.root)
        key = self.eval_expr(node.key)
        return self._path_get(root, key)

    def _get_path_literal(self, node: P.EPathLiteral) -> V.Value:
        # ``'a\b`` — get the value of variable ``a\b`` (special)
        # In Arturo, a path literal is an unevaluated path expression.
        # For now treat like getting root with key from a\b path.
        return self.ctx.get(node.root + "\\" + node.key)

    def _path_get(self, root, key) -> V.Value:
        key_name = self._key_to_str(key)
        if isinstance(root, V.VDictionary):
            if key_name in root.items:
                return root.items[key_name]
            return V.Null()
        if isinstance(root, V.VObject):
            if key_name in root.fields:
                return root.fields[key_name]
            return V.Null()
        if isinstance(root, V.VBlock):
            try:
                idx = int(key_name)
                if 0 <= idx < len(root.items):
                    item = root.items[idx]
                    if isinstance(item, V.Value):
                        return item
                    return self.eval_expr(item)
            except (ValueError, IndexError):
                pass
            return V.Null()
        return V.Null()

    def _key_to_str(self, key) -> str:
        if isinstance(key, V.VString):
            return key.data
        if isinstance(key, V.VWord):
            return key.name
        if isinstance(key, V.VLiteral):
            return key.name
        if isinstance(key, V.VInteger):
            return str(key.data)
        return str(getattr(key, "data", ""))

    def _set_path(self, path_node, value) -> None:
        # path_node is EPath starting from EVar/EValue/ELiteral root.
        # Walk to the second-to-last component, then assign to the last.
        if not isinstance(path_node, P.EPath):
            # Direct assignment (rare)
            return
        # Drill into root
        nodes = self._flatten_path(path_node)
        # nodes: [root, key1, key2, ...]
        if len(nodes) < 2:
            return
        # Evaluate all but the last
        target = self.eval_expr(nodes[0])
        for n in nodes[1:-1]:
            key = self.eval_expr(n)
            key_name = self._key_to_str(key)
            if isinstance(target, V.VDictionary):
                # Ensure key exists (default null)
                if key_name not in target.items:
                    target.items[key_name] = V.Null()
                target = target.items[key_name]
            elif isinstance(target, V.VObject):
                if key_name not in target.fields:
                    target.fields[key_name] = V.Null()
                target = target.fields[key_name]
            else:
                return
        last_key = self.eval_expr(nodes[-1])
        last_key_name = self._key_to_str(last_key)
        if isinstance(target, V.VDictionary):
            target.items[last_key_name] = value
        elif isinstance(target, V.VObject):
            target.fields[last_key_name] = value

    def _flatten_path(self, node: P.EPath) -> List[object]:
        """Turn ``a\b\c`` into ``[EVar(a), ELiteral(b), ELiteral(c)]``."""
        parts: List[object] = []
        # Walk down the path, collecting left-to-right.
        def walk(n, acc):
            if isinstance(n, P.EPath):
                walk(n.root, acc)
                acc.append(n.key)
            else:
                acc.append(n)
        walk(node, parts)
        return parts
