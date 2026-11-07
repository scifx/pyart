"""
library.py - the symbol library (builtin functions and constants).

A :class:`Library` maps names to :class:`~arturo.values.Function` values so
that the parser can ask for arities (which drives expression grouping) and
the evaluator can resolve calls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import values as V


class VersionedDict(dict):
    """A ``dict`` that counts its *effective* mutations.

    Caches keyed on language state (compiled AST trees, arity snapshots) need
    to notice any change to it, but writing back the value that is already
    there is not a change: bumping the counter for that would invalidate every
    cached tree on every parse.
    """

    __slots__ = ("version",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.version = 0

    def __setitem__(self, key, value):
        if key not in self or dict.__getitem__(self, key) != value:
            self.version += 1
        super().__setitem__(key, value)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.version += 1

    def pop(self, *args):
        present = args[0] in self if args else False
        result = super().pop(*args)
        if present:
            self.version += 1
        return result

    def update(self, *args, **kwargs):
        changed = False
        for key, value in dict(*args, **kwargs).items():
            if key not in self or dict.__getitem__(self, key) != value:
                changed = True
            dict.__setitem__(self, key, value)
        if changed:
            self.version += 1

    def clear(self):
        if self:
            self.version += 1
        super().clear()

    def setdefault(self, key, default=None):
        if key not in self:
            self.version += 1
            return super().setdefault(key, default)
        return dict.__getitem__(self, key)


class Library:
    def __init__(self):
        self._fns: Dict[str, V.Function] = {}
        self._types: Dict[str, Dict[str, Any]] = {}
        self.constants: Dict[str, V.Value] = {}
        # word -> arity of user functions defined so far (Arturo's TmpArities)
        self.user_arities: Dict[str, int] = VersionedDict()
        self._version = 0

    # -- registration ----------------------------------------------------
    def register(self, name, arity, impl, attrs=None):
        self._fns[name] = V.Function(
            name=name, params=[], arity=arity, impl=impl, attrs=set(attrs or ())
        )
        self._version += 1

    def register_value(self, name: str, value: V.Function) -> None:
        self._fns[name] = value
        self._version += 1

    def alias(self, name, target):
        fn = self._fns.get(target)
        if fn is None:
            return
        self._fns[name] = V.Function(
            name=name, params=[], arity=fn.arity, impl=fn.impl, attrs=set(fn.attrs)
        )
        self._version += 1

    # -- lookup ----------------------------------------------------------
    def lookup(self, name) -> Optional[V.Function]:
        return self._fns.get(name)

    def constant(self, name: str) -> Optional[V.Value]:
        return self.constants.get(name)

    def has(self, name: str) -> bool:
        return name in self._fns or name in self.constants

    def names(self) -> List[str]:
        return list(self._fns.keys())

    def items(self):
        return self._fns.items()

    def __contains__(self, name):
        return self.has(name)

    # -- custom types ----------------------------------------------------
    def register_type(self, name, methods):
        self._types[name] = methods

    def lookup_type(self, name):
        return self._types.get(name)
