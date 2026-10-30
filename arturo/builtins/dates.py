"""
dates.py - Arturo's date & time builtins (port of ``src/library/Dates.nim``).
"""
from __future__ import annotations

import datetime

from .. import values as V
from ..nimtime import as_datetime
from . import attr, builtin, fail, impl, to_int


def _date_of(value) -> datetime.datetime:
    d = as_datetime(value)
    if d is None:
        fail("cannot use value as a date", "Type Error")
    return d


def _make_day_predicate(name: str, weekday: int):
    def predicate(ev, args):
        d = _date_of(args[0])
        return V.Logical(d.isoweekday() == weekday)

    predicate.__name__ = f"_{name}"
    return predicate


for _name, _weekday in (
    ("monday?", 1),
    ("tuesday?", 2),
    ("wednesday?", 3),
    ("thursday?", 4),
    ("friday?", 5),
    ("saturday?", 6),
    ("sunday?", 7),
):
    impl(_name)(_make_day_predicate(_name, _weekday))


@impl("past?")
def _past(ev, args):
    now = datetime.datetime.now().astimezone()
    return V.Logical(now > _date_of(args[0]))


@impl("future?")
def _future(ev, args):
    now = datetime.datetime.now().astimezone()
    return V.Logical(now < _date_of(args[0]))


def _shift(ev, when: datetime.datetime, sign: int) -> V.Date:
    """Apply the ``.years/.months/.weeks/.days/.hours/...`` attribute."""
    for name in ("years", "months", "weeks", "days", "hours", "minutes", "seconds"):
        value = attr(ev, name, None)
        if value is None:
            continue
        step = sign * to_int(value)
        if name == "years":
            try:
                return V.Date(when.replace(year=when.year + step))
            except ValueError:
                return V.Date(when.replace(year=when.year + step, day=28))
        if name == "months":
            month = when.month - 1 + step
            year = when.year + month // 12
            month = month % 12 + 1
            day = min(when.day, [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30,
                                 31, 31, 30, 31, 30, 31][month - 1])
            return V.Date(when.replace(year=year, month=month, day=day))
        return V.Date(when + datetime.timedelta(**{name: step}))
    return V.Date(when + datetime.timedelta(days=sign))


@builtin("before", arity=1,
         attrs=["nanoseconds", "milliseconds", "seconds", "minutes", "hours",
                "days", "weeks", "months", "years"])
def _before(ev, args):
    return _shift(ev, _date_of(args[0]), -1)


@builtin("after", arity=1,
         attrs=["nanoseconds", "milliseconds", "seconds", "minutes", "hours",
                "days", "weeks", "months", "years"])
def _after(ev, args):
    return _shift(ev, _date_of(args[0]), 1)
