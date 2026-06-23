"""
library.py - Pluggable library / module system.

A :class:`Library` holds a name -> :class:`values.VBuiltinFunction` map.
Modules are callables that register functions on a library.  The default
module set is :data:`DEFAULT_MODULES`.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


class Module:
    """A library module: a named function that registers functions on a library."""

    def __init__(self, name: str, register_fn: Callable[["Library"], None]):
        self.name = name
        self.register = register_fn


class Library:
    def __init__(self):
        self._fns: Dict[str, Any] = {}
        # Custom-type definitions: name -> dict(methods, etc.)
        self._types: Dict[str, Dict[str, Any]] = {}

    # -- registration --------------------------------------------------------
    def register(self, name, arity, impl, attrs=None):
        from . import values as V
        self._fns[name] = V.Builtin(name=name, arity=arity, impl=impl, attrs=attrs or {})

    def alias(self, name, target):
        if target in self._fns:
            fn = self._fns[target]
            self._fns[name] = type(fn)(
                name=fn.name, arity=fn.arity, impl=fn.impl, attrs=fn.attrs
            )

    def lookup(self, name):
        return self._fns.get(name)

    def names(self):
        return list(self._fns.keys())

    def __contains__(self, name):
        return name in self._fns

    # -- custom types ---------------------------------------------------------
    def register_type(self, name, methods):
        """Register a custom type with its methods."""
        self._types[name] = methods

    def lookup_type(self, name):
        return self._types.get(name)
