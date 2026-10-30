"""
nimtime.py - bridge between Arturo/Nim date patterns and Python's ``datetime``.

Arturo formats dates with the Nim ``std/times`` pattern language
(``yyyy-MM-dd'T'HH:mm:sszzz``), which is *not* ``strftime``.  This module
translates the patterns in both directions and offers lenient parsing.
"""
from __future__ import annotations

import datetime as _dt

# Longest patterns first so that ``yyyy`` wins over ``yy`` etc.
_PATTERNS = [
    ("dddd", "%A"),
    ("ddd", "%a"),
    ("dd", "%d"),
    ("d", "%-d"),
    ("dddd", "%A"),
    ("MMMM", "%B"),
    ("MMM", "%b"),
    ("MM", "%m"),
    ("M", "%-m"),
    ("yyyy", "%Y"),
    ("yy", "%y"),
    ("YYYY", "%G"),
    ("HH", "%H"),
    ("H", "%-H"),
    ("hh", "%I"),
    ("h", "%-I"),
    ("mm", "%M"),
    ("m", "%-M"),
    ("ss", "%S"),
    ("s", "%-S"),
    ("tt", "%p"),
    ("t", "%p"),
    ("zzz", "%z"),
    ("zz", "%z"),
    ("z", "%z"),
    ("fff", "%f"),
    ("fffffff", "%f"),
]


def nim_to_strftime(pattern: str) -> str:
    """Translate a Nim ``times`` pattern into a Python ``strftime`` one."""
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "'":
            j = pattern.find("'", i + 1)
            if j == -1:
                out.append(pattern[i + 1:])
                break
            out.append(pattern[i + 1:j].replace("%", "%%"))
            i = j + 1
            continue
        for token, repl in _PATTERNS:
            if pattern.startswith(token, i):
                out.append(repl)
                i += len(token)
                break
        else:
            out.append("%%" if ch == "%" else ch)
            i += 1
    return "".join(out)


def parse(text: str, pattern: str | None = None) -> _dt.datetime:
    """Parse ``text`` using a Nim pattern (or a set of common ISO formats)."""
    text = text.strip()
    if pattern:
        return _dt.datetime.strptime(text, nim_to_strftime(pattern))
    candidates = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in candidates:
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"cannot parse date: {text!r}")


def format(value: _dt.datetime, pattern: str | None = None) -> str:
    """Format ``value`` using a Nim pattern."""
    if pattern is None:
        pattern = "yyyy-MM-dd'T'HH:mm:sszzz"
    return value.strftime(nim_to_strftime(pattern))


def as_datetime(value) -> _dt.datetime | None:
    """Best-effort conversion of an Arturo value to a ``datetime``."""
    data = getattr(value, "data", value)
    if isinstance(data, _dt.datetime):
        return data
    if isinstance(data, _dt.date) and not isinstance(data, _dt.datetime):
        return _dt.datetime(data.year, data.month, data.day)
    return None


_FIELDS = {
    "year": lambda d: d.year,
    "month": lambda d: d.month,
    "day": lambda d: d.day,
    "hour": lambda d: d.hour,
    "minute": lambda d: d.minute,
    "second": lambda d: d.second,
    "microsecond": lambda d: d.microsecond,
    "dayofweek": lambda d: d.isoweekday(),          # 1 = Monday
    "dayofyear": lambda d: int(d.strftime("%j")),
    "weekofyear": lambda d: int(d.strftime("%W")),
    "quarter": lambda d: (d.month - 1) // 3 + 1,
    "isoweekday": lambda d: d.isoweekday(),
    "weekday": lambda d: d.isoweekday(),
    "monthname": lambda d: d.strftime("%B"),
    "dayname": lambda d: d.strftime("%A"),
    "utc": lambda d: d.astimezone(_dt.timezone.utc).replace(tzinfo=None),
    "unix": lambda d: int(d.timestamp()),
}


def attribute(value, name: str):
    """Return the date component ``name`` (``None`` when unknown)."""
    d = as_datetime(value)
    if d is None:
        return None
    getter = _FIELDS.get(name)
    if getter is None:
        return None
    return getter(d)
