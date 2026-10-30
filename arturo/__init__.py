"""
arturo - a Python implementation of the Arturo programming language.

Public API::

    from arturo import Interpreter
    Interpreter().exec('print "Hello world!"')

The implementation follows Arturo's own architecture:

    parser.py     source  ->  Block of values      (port of vm/parse.nim)
    ast.py        Block   ->  Node tree            (port of vm/ast.nim)
    evaluator.py  Node    ->  evaluated values     (port of vm/eval.nim + exec.nim)
    builtins/     the standard library
"""
from __future__ import annotations

import io
import math
import sys

try:  # allow arbitrarily long integers when printing/parsing
    sys.set_int_max_str_digits(0)
except AttributeError:  # pragma: no cover - Python < 3.11
    pass
sys.setrecursionlimit(20000)
from typing import List, Optional, TextIO

from . import ast as _ast
from . import evaluator as _E
from . import library as _L
from . import parser as _P
from . import values as V

__all__ = ["Interpreter", "run", "eval", "values", "parser", "ast", "evaluator",
           "library", "Error", "ArturoError"]

ArturoError = _E.ArturoError
Error = _E.ArturoError


class Interpreter:
    """A reusable Arturo interpreter."""

    def __init__(self, out: Optional[TextIO] = None, argv: Optional[List[str]] = None):
        self.library = _L.Library()
        from .builtins import install

        install(self.library)
        from .builtins.numbers import register_constants

        register_constants(self.library)
        self.context = _E.Context(self.library, out=out)
        for _name, _value in self.library.constants.items():
            self.context.set(_name, _value)
        self.context.argv = argv or []
        self.context.path = ["<script>"]
        self.evaluator = _E.Evaluator(self.context)
        self.context.evaluator = self.evaluator

    # -- running code ----------------------------------------------------
    def exec(self, source: str, path: str = "<script>") -> Optional[V.Value]:
        """Parse and evaluate ``source``, returning its last value."""
        self.context.path = [path]
        block = _P.parse(source)
        tree = _ast.build(block, self.library, self.context.syms)
        try:
            return self.evaluator.eval_node(tree)
        except _E.ReturnSignal as ret:
            return ret.value
        except _E.BreakSignal:
            return V.NULL
        except _E.ContinueSignal:
            return V.NULL

    def exec_file(self, path: str) -> Optional[V.Value]:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.context.cwd = None
        return self.exec(source, path=path)

    # -- helpers ---------------------------------------------------------
    def get(self, name: str) -> Optional[V.Value]:
        return self.context.syms.get(name)

    def set(self, name: str, value: V.Value) -> None:
        self.context.set(name, value)


def run(source: str, out: Optional[TextIO] = None) -> Optional[V.Value]:
    """Run Arturo source with a fresh interpreter."""
    return Interpreter(out=out).exec(source)


def eval_(source: str, out: Optional[TextIO] = None):
    return run(source, out=out)


eval = eval_
