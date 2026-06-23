"""
arturo_mini - a tiny Arturo interpreter in Python.

Public API:

* :class:`Interpreter` - run source code
* :func:`run` - convenience helper
* :mod:`values`, :mod:`parser`, :mod:`evaluator`, :mod:`library`, :mod:`stdlib`
"""
from __future__ import annotations

from typing import List, Optional

from . import evaluator as _E
from . import library as _L
from . import parser as _P
from . import stdlib as _stdlib
from . import values as V


__all__ = [
    "Interpreter",
    "run",
    "eval",
    "values",
    "parser",
    "evaluator",
    "library",
    "stdlib",
]


class Interpreter:
    """A re-usable Arturo interpreter."""

    def __init__(self, modules: Optional[List[_stdlib.Module]] = None):
        self.library = _L.Library()
        _stdlib.load_modules(
            self.library,
            modules or _stdlib.DEFAULT_MODULES,
        )
        self.context = _E.Context(self.library)
        # Names that have been bound to user functions in this session
        # (so future ``f args`` calls are parsed as function calls).
        self._user_functions: set = set()

    def exec(self, source: str) -> Optional[V.Value]:
        parser = _P.Parser(source, self.library._fns, known_functions=self._user_functions)
        ast = parser.parse()
        ev = _E.Evaluator(self.context)
        try:
            return ev.exec_program(ast)
        except _E.BreakSignal:
            return V.Null()
        except _E.ContinueSignal:
            return V.Null()
        finally:
            # Carry over any newly defined functions so subsequent execs
            # parse them as calls.
            self._user_functions |= parser._user_functions

    def get(self, name: str) -> Optional[V.Value]:
        return self.context.scope.get(name)

    def set(self, name: str, value: V.Value) -> None:
        self.context.set(name, value)


def run(source: str) -> Optional[V.Value]:
    """Run Arturo source code with a fresh interpreter."""
    return Interpreter().exec(source)


def eval_(source: str) -> Optional[V.Value]:
    return run(source)


# Backwards-compat alias (some tests import ``eval``).
eval = eval_
