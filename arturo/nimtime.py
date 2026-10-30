"""nimtime.py - Arturo/Nim date patterns.

Arturo formats and parses dates with the Nim ``std/times`` pattern language
(``yyyy-MM-dd'T'HH:mm:sszzz``), which is *not* ``strftime`` (``m`` is the
minute, ``M`` the month...).  Python's ``strptime`` also does not accept the
"no padding" directives, so both directions are implemented here by hand.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_DAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

# Longest patterns first (so ``yyyy`` wins over ``yy``, ``MMMM`` over ``MM``...)
_TOKENS = [
    "fffffffff", "ffffff", "fff",
    "yyyy", "yyy", "yy", "YYYY", "YYY", "YY",
    "MMMM", "MMM", "MM", "M",
    "dddd", "ddd", "dd", "d",
    "HH", "H", "hh", "h",
    "mm", "m", "ss", "s",
    "tt", "t", "TT", "T",
    "zzz", "zz", "z",
    "y", "Y",
]


def _tokenize(pattern: str):
    """Yield ``(token, literal)`` pairs; literals come from quoted parts."""
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "'":
            j = pattern.find("'", i + 1)
            if j == -1:
                yield None, pattern[i + 1:]
                return
            yield None, pattern[i + 1:j]
            i = j + 1
            continue
        for tok in _TOKENS:
            if pattern.startswith(tok, i):
                yield tok, None
                i += len(tok)
                break
        else:
            # a stray letter that is not part of a token is literal
            yield None, ch
            i += 1


def format(value: _dt.datetime, pattern: Optional[str] = None) -> str:
    """Format ``value`` using a Nim ``times`` pattern."""
    if pattern is None:
        pattern = "yyyy-MM-dd'T'HH:mm:sszzz"
    out = []
    for tok, literal in _tokenize(pattern):
        if literal is not None:
            out.append(literal)
            continue
        if tok in ("yyyy",):
            out.append("%04d" % value.year)
        elif tok in ("yyy", "yy", "y"):
            out.append("%02d" % (value.year % 100))
        elif tok in ("YYYY", "YYY", "YY", "Y"):
            out.append("%04d" % value.isocalendar()[0])
        elif tok == "MMMM":
            out.append(_MONTHS[value.month - 1])
        elif tok == "MMM":
            out.append(_MONTHS[value.month - 1][:3])
        elif tok == "MM":
            out.append("%02d" % value.month)
        elif tok == "M":
            out.append(str(value.month))
        elif tok == "dddd":
            out.append(_DAYS[value.weekday()])
        elif tok == "ddd":
            out.append(_DAYS[value.weekday()][:3])
        elif tok == "dd":
            out.append("%02d" % value.day)
        elif tok == "d":
            out.append(str(value.day))
        elif tok == "HH":
            out.append("%02d" % value.hour)
        elif tok == "H":
            out.append(str(value.hour))
        elif tok in ("hh", "h"):
            hour = value.hour % 12 or 12
            out.append("%02d" % hour if tok == "hh" else str(hour))
        elif tok == "mm":
            out.append("%02d" % value.minute)
        elif tok == "m":
            out.append(str(value.minute))
        elif tok == "ss":
            out.append("%02d" % value.second)
        elif tok == "s":
            out.append(str(value.second))
        elif tok in ("tt", "TT"):
            out.append("AM" if value.hour < 12 else "PM")
        elif tok in ("t", "T"):
            out.append("A" if value.hour < 12 else "P")
        elif tok == "fff":
            out.append("%03d" % (value.microsecond // 1000))
        elif tok == "ffffff":
            out.append("%06d" % value.microsecond)
        elif tok == "fffffffff":
            out.append("%09d" % (value.microsecond * 1000))
        elif tok in ("zzz", "zz", "z"):
            off = value.utcoffset()
            minutes = int(off.total_seconds() // 60) if off else 0
            sign = "+" if minutes >= 0 else "-"
            minutes = abs(minutes)
            if tok == "zzz":
                out.append("%s%02d:%02d" % (sign, minutes // 60, minutes % 60))
            elif tok == "zz":
                out.append("%s%02d%02d" % (sign, minutes // 60, minutes % 60))
            else:
                out.append("%s%02d" % (sign, minutes // 60))
        else:  # pragma: no cover - every token is covered above
            out.append(tok)
    return "".join(out)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_TZ_NAMES = {
    "UTC": 0, "GMT": 0, "Z": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "CET": 1, "CEST": 2,
    "BST": 1, "IST": 5.5, "JST": 9, "AEST": 10, "AEDT": 11,
}


def _compile(pattern: str):
    """Turn a Nim pattern into ``(regex, field order)``."""
    parts = []
    fields = []
    for tok, literal in _tokenize(pattern):
        if literal is not None:
            if literal.strip() == "":
                parts.append(r"\s*")
            else:
                parts.append(re.escape(literal))
            continue
        if tok in ("yyyy", "YYYY"):
            parts.append(r"(\d{4})")
        elif tok in ("yyy", "yy", "y", "YYY", "YY", "Y"):
            parts.append(r"(\d{1,4})")
        elif tok == "MMMM":
            parts.append(r"([A-Za-z]+)")
        elif tok == "MMM":
            parts.append(r"([A-Za-z]+)")
        elif tok in ("MM", "M"):
            parts.append(r"(\d{1,2})")
        elif tok in ("dddd", "ddd"):
            parts.append(r"([A-Za-z]+)")
        elif tok in ("dd", "d"):
            parts.append(r"(\d{1,2})")
        elif tok in ("HH", "H", "hh", "h"):
            parts.append(r"(\d{1,2})")
        elif tok in ("mm", "m"):
            parts.append(r"(\d{1,2})")
        elif tok in ("ss", "s"):
            parts.append(r"(\d{1,2})")
        elif tok in ("fff", "ffffff", "fffffffff"):
            parts.append(r"(\d{1,9})")
        elif tok in ("tt", "TT", "t", "T"):
            parts.append(r"([AaPp][Mm]?)")
        elif tok in ("zzz", "zz", "z"):
            parts.append(r"([+-]\d{1,2}:?\d{0,2}|Z|[A-Za-z]{2,5})")
        else:  # pragma: no cover
            parts.append(re.escape(tok))
        fields.append(tok)
    return re.compile("^" + "".join(parts) + "$"), fields


def parse(text: str, pattern: Optional[str] = None) -> _dt.datetime:
    """Parse ``text`` using a Nim pattern (or a set of common formats)."""
    text = text.strip()
    if pattern:
        rx, fields = _compile(pattern)
        match = rx.match(text)
        if match is None:
            raise ValueError(f"cannot parse date: {text!r} (pattern {pattern!r})")
        values = dict(zip(fields, match.groups()))

        def num(*names, default=None):
            for name in names:
                if name in values:
                    return int(values[name])
            return default

        year = num("yyyy", "yyy", "yy", "y", "YYYY", "YYY", "YY", "Y", default=0)
        if year < 100:
            year += 2000 if year < 70 else 1900
        month = 1
        if "MMMM" in values or "MMM" in values:
            name = values.get("MMMM") or values.get("MMM")
            month = _month_from_name(name)
        else:
            month = num("MM", "M", default=1)
        day = num("dd", "d", default=1)
        hour = num("HH", "H", "hh", "h", default=0)
        minute = num("mm", "m", default=0)
        second = num("ss", "s", default=0)
        micro = 0
        for key in ("fffffffff", "ffffff", "fff"):
            if key in values:
                raw = values[key]
                micro = int((raw + "0" * 9)[:9]) // 1000
                break
        ampm = values.get("tt") or values.get("TT") or values.get("t") or values.get("T")
        if ampm:
            ampm = ampm.upper()
            if ampm.startswith("P") and hour < 12:
                hour += 12
            elif ampm.startswith("A") and hour == 12:
                hour = 0
        tzinfo = None
        raw_tz = values.get("zzz") or values.get("zz") or values.get("z")
        if raw_tz:
            tzinfo = _parse_tz(raw_tz)
        return _dt.datetime(year, month, day, hour, minute, second, micro,
                            tzinfo=tzinfo)
    candidates = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]
    for fmt in candidates:
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"cannot parse date: {text!r}")


def _month_from_name(name: str) -> int:
    name = name.strip().lower()
    for i, full in enumerate(_MONTHS, start=1):
        if full.lower() == name or full[:3].lower() == name[:3]:
            return i
    raise ValueError(f"unknown month: {name!r}")


def _parse_tz(raw: str):
    raw = raw.strip()
    if raw.upper() in _TZ_NAMES:
        hours = _TZ_NAMES[raw.upper()]
        return _dt.timezone(_dt.timedelta(hours=hours))
    sign = -1 if raw.startswith("-") else 1
    body = raw[1:].replace(":", "")
    if len(body) >= 4:
        hours, minutes = int(body[:2]), int(body[2:4])
    elif len(body) == 2:
        hours, minutes = int(body), 0
    elif len(body) in (1, 3):
        hours, minutes = int(body[0]), int(body[1:] or 0)
    else:
        return None
    return _dt.timezone(sign * _dt.timedelta(hours=hours, minutes=minutes))


def as_datetime(value) -> Optional[_dt.datetime]:
    """Best-effort conversion of a value to a ``datetime``."""
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
