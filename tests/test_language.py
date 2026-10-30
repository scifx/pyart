"""
test_language.py - behavioural test suite for the Python port of Arturo.

Every expectation in this file was cross-checked against the reference
implementation (Arturo ``0.10.1-dev``, see ``benchmarks/README.md``).

Run with::

    python3 -m pytest tests -q
    # or, without pytest
    python3 tests/test_language.py
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arturo import Interpreter, ArturoError  # noqa: E402


def run(source: str) -> str:
    """Execute ``source`` and return everything it printed."""
    buf = io.StringIO()
    Interpreter(out=buf).exec(source)
    return buf.getvalue()


def check(source: str, expected: str) -> None:
    try:
        actual = run(source)
    except ArturoError as exc:
        raise AssertionError(f"{source!r}\n  error: {exc}") from None
    assert actual == expected, f"{source!r}\n  expected {expected!r}\n  actual   {actual!r}"


# ---------------------------------------------------------------------------
# values, literals and printing
# ---------------------------------------------------------------------------
CASES = [
    ('print "Hello world!"', "Hello world!\n"),
    ("print 42", "42\n"),
    ("print 1.5", "1.5\n"),
    ("print 1.0", "1.0\n"),
    ("print true", "true\n"),
    ("print null", "null\n"),
    ("print ø", "null\n"),
    ("print 'a", "a\n"),
    ("print [1 2 3]", "1 2 3 \n"),
    ("print [1 [2 3]]", "1 [2 3] \n"),
    ("print #[]", "[]\n"),
    ("print #[a: 1 b: 2]", "[a:1 b:2]\n"),
    ("print pi", "3.141592653589793\n"),
    ("print epsilon", "2.718281828459045\n"),
    ("print infinite", "∞\n"),
    ("print type 1", ":integer\n"),
    ("print type \"a\"", ":string\n"),
    ("print @[1 2]", "1 2 \n"),
    ("print @[1 + 2]", "3 \n"),
    ("x: 3 print @[x x+1]", "3 4 \n"),
]

# ---------------------------------------------------------------------------
# right-to-left arithmetic, no operator precedence
# ---------------------------------------------------------------------------
ARITHMETIC = [
    ("print 1 + 2 * 3", "7\n"),
    ("print 2 * 3 + 4", "14\n"),
    ("print (2 * 3) + 4", "10\n"),
    ("print 1/2", "0\n"),
    ("print 7//2", "3.5\n"),
    ("print 1:2", "1/2\n"),
    ("print 2^10", "1024\n"),
    ("print abs neg 5", "5\n"),
]

# ---------------------------------------------------------------------------
# blocks, iterators and closures
# ---------------------------------------------------------------------------
ITERATORS = [
    ("print map 1..3 => [&*2]", "2 4 6 \n"),
    ("print map 1..3 'x -> x*2", "2 4 6 \n"),
    ("print select 1..10 => [even? &]", "2 4 6 8 10 \n"),
    ("print select.first 1..10 => even?", "2 \n"),
    ("print fold 1..5 [a b][a+b]", "15\n"),
    ("print fold 1..4 => add", "10\n"),
    ("loop 1..3 'x [print x]", "1\n2\n3\n"),
    ("print sum 1..10", "55\n"),
    ("print product 1..4", "24\n"),
    ("print sum [1 2 3]", "6\n"),
    ("print average [1 2 3]", "2.0\n"),
    ("print max [3 1 4]", "4\n"),
]

# ---------------------------------------------------------------------------
# conditionals
# ---------------------------------------------------------------------------
CONDITIONALS = [
    ('print if 0 ["y"]', "y\n"),
    ('x: 2 if? x>3 [print "big"] else [print "small"]', "small\n"),
    ('x: 5 if? x>3 [print "big"] else [print "small"]', "big\n"),
    ('print when [false -> 1 true -> 2]', "2\n"),
    ('print any? @[false 3=4 2>1]', "true\n"),
    ('print all? @[true 1=1]', "true\n"),
    ('print not? 1 = 2', "true\n"),
]

# ---------------------------------------------------------------------------
# functions
# ---------------------------------------------------------------------------
FUNCTIONS = [
    ("f: function [x][x*2] print f 3", "6\n"),
    ("g: $[x y][x+y] print g 1 2", "3\n"),
    ("f: function [x]-> x + 1 print f 1", "2\n"),
    (
        "fib: function [n][if n<2 -> return n return (fib n-1) + (fib n-2)]\n"
        "print fib 10",
        "55\n",
    ),
    ("multiply: function [x y][x*y] print call 'multiply [3 5]", "15\n"),
]

# ---------------------------------------------------------------------------
# strings
# ---------------------------------------------------------------------------
STRINGS = [
    ('print upper "abc"', "ABC\n"),
    ('print split "abc"', "a b c \n"),
    ('print split.words "a b  c"', "a b c \n"),
    ('print split.every: 2 "abcd"', "ab cd \n"),
    ('print join.with: "," ["a" "b"]', "a,b\n"),
    ('print replace "hello" "l" "L"', "heLLo\n"),
    ('print "a" ++ "b"', "ab\n"),
    ('print match "x: 123, y: 456" {/[0-9]+/}', "123 456 \n"),
    ('print match.bounds "hELlo wORLd" {/[A-Z]+/}', "1..2 7..9 \n"),
    ('print pad "ab" 5', "   ab\n"),
    ('print size "hello"', "5\n"),
    ('print index "aback" "a"', "0\n"),
]

# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------
COLLECTIONS = [
    ("print sort [3 1 2]", "1 2 3 \n"),
    ("print sort.descending [3 1 2]", "3 2 1 \n"),
    ("print reverse [1 2 3]", "3 2 1 \n"),
    ("print unique [1 1 2]", "1 2 \n"),
    ("print flatten [1 [2 [3]]]", "1 2 3 \n"),
    ("print couple [a b] [1 2]", "[a 1] [b 2] \n"),
    ("print repeat [1 2] 2", "1 2 1 2 \n"),
    ("a: [1 2 3] 'a ++ 4 print a", "1 2 3 4 \n"),
    ("a: [1 2 3] print pop 'a", "3\n"),
    ("print keys #[a: 1 b: 2]", "a b \n"),
    ("print values #[a: 1 b: 2]", "1 2 \n"),
    ("print size [1 2 3]", "3\n"),
]

# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------
DATES = [
    ('d: to :date.format:"dd-MM-yyyy" "25-12-2021" print d\\year', "2021\n"),
    ('print to :string .format:"yyyy" to :date "2019-07-04"', "2019\n"),
    ('print monday? to :date "2019-01-07"', "true\n"),
]

# ---------------------------------------------------------------------------
# in-place semantics and scoping
# ---------------------------------------------------------------------------
SEMANTICS = [
    ("x: 1 inc 'x print x", "2\n"),
    ("x: 1 x: x + 1 print x", "2\n"),
    ("x: 0 while ø [ x: x+1 if x>2 -> break ] print x", "3\n"),
    ("i: 0 until [i: i+1][i = 3] print i", "3\n"),
    ("[a b]: [1 2] print a print b", "1\n2\n"),
    ("print 1+2", "3\n"),
]

ALL_CASES = (CASES + ARITHMETIC + ITERATORS + CONDITIONALS + FUNCTIONS
             + STRINGS + COLLECTIONS + DATES + SEMANTICS)


def test_language() -> None:
    failures = []
    for source, expected in ALL_CASES:
        try:
            check(source, expected)
        except AssertionError as exc:  # pragma: no cover - reported below
            failures.append(str(exc))
    assert not failures, "failed cases:\n\n" + "\n\n".join(failures)


def main() -> int:
    failed = 0
    for source, expected in ALL_CASES:
        try:
            check(source, expected)
            print(f"✓ {source}")
        except AssertionError as exc:
            failed += 1
            print(f"✗ {exc}")
    print(f"\n{len(ALL_CASES) - failed}/{len(ALL_CASES)} language checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
