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
import json
import os
import re
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
    ('do.times: 3 [print "repeat"]', "repeat\nrepeat\nrepeat\n"),
    ('do.times: 0 [print "never"] print "done"', "done\n"),
    ("print sum 1..10", "55\n"),
    ("print product 1..4", "24\n"),
    ("f: function [n][counter: 0 do.times:n [counter: counter + 1] counter] print map 1..3 'n -> f n", "1 2 3 \n"),
    ("print sum [1 2 3]", "6\n"),
    ("print average [1 2 3]", "2.0\n"),
    ("print max [3 1 4]", "4\n"),
]

# ---------------------------------------------------------------------------
# reflection and runtime documentation
# ---------------------------------------------------------------------------
REFLECTION = [
    ("meta: info.get 'print print meta\\name print meta\\module print get meta\\example 0",
     'print\nIo\nprint "Hello world!"          ; Hello world!\n'),
    ("meta: info.get '++ print meta\\name", "append\n"),
    ("info.get 'map | get 'example | get 0 | print",
     "print map 1..5 [x][\n    2*x\n]\n; 2 4 6 8 10\n"),
    ("info 'print",
     "|" + "-" * 80 + "\n"
     "|          print  :function                                                   Io\n"
     "|" + "-" * 80 + "\n"
     "|                 print given value to screen with newline\n"
     "|" + "-" * 80 + "\n"
     "|          usage  print value :any\n|\n"
     "|        options  .lines -> print each value in block in a new line\n|\n"
     "|        returns  :nothing\n"
     "|" + "-" * 80 + "\n"),
    ("pause 0:s print \"awake\"", "awake\n"),
    ("print sys\\version > 0.9.0 print set? 'abs", "true\ntrue\n"),
    ("define :cat [init: method [name][null] meow: method [][null]]\n"
     "cat: to :cat #[] print methods cat", "init meow \n"),
    ("define :cat [meow: method [][null]] cat: to :cat #[]\n"
     "info.get 'cat\\meow | get 'name | print", "meow\n"),
    ('f: function [x :integer][x] print f 7', "7\n"),
    ("f: function [x :integer][x] m: info.get 'f print m\\args print m\\returns",
     "[x:[:integer]]\n:nothing \n"),
    ('''f: function [x :integer][\n    ;; description: « returns the input, with documented options\n    ;; options: [\n    ;;   multiplier: :integer « multiplier to apply\n    ;; ]\n    ;; returns: :integer\n    ;; example: {\n    ;;   f 3\n    ;; }\n    x\n]\nm: info.get 'f\nprint m\\description\nprint m\\args\nprint m\\attrs\nprint m\\returns\nprint get m\\example 0''',
     "returns the input, with documented options\n[x:[:integer]]\n"
     "[multiplier:[types:[:integer] description:multiplier to apply]]\n"
     ":integer \nf 3\n"),
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

ALL_CASES = (CASES + ARITHMETIC + ITERATORS + REFLECTION + CONDITIONALS + FUNCTIONS
             + STRINGS + COLLECTIONS + DATES + SEMANTICS)


def test_language() -> None:
    failures = []
    for source, expected in ALL_CASES:
        try:
            check(source, expected)
        except AssertionError as exc:  # pragma: no cover - reported below
            failures.append(str(exc))
    assert not failures, "failed cases:\n\n" + "\n\n".join(failures)


def test_typed_function_rejects_wrong_argument_type() -> None:
    interp = Interpreter(out=io.StringIO())
    try:
        interp.exec('f: function [x :integer][x] f "not an integer"')
    except ArturoError as exc:
        assert exc.kind == "Assertion Failed", str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("typed function accepted a string for :integer")


def test_arg_returns_runtime_argv() -> None:
    output = io.StringIO()
    Interpreter(out=output, argv=["one", "two"]).exec("print arg")
    assert output.getvalue() == "one two \n"


def test_reflection_module_examples() -> None:
    output = io.StringIO()
    interp = Interpreter(out=output)
    interp.exec('1 2 3 "done" print stack')
    assert output.getvalue() == "1 2 3 done \n"

    output = io.StringIO()
    Interpreter(out=output).exec(
        'f: function [x][print attr? "with" print attr "with" x] f.with: 7 1'
    )
    assert output.getvalue() == "true\n7\n"

    output = io.StringIO()
    interp = Interpreter(out=output)
    interp.exec('benchmark [1 + 2]')
    assert re.fullmatch(r"\[benchmark\] time: \d+\.\d{3}ms\n", output.getvalue())

    interp = Interpreter(out=io.StringIO())
    interp.exec("elapsed: benchmark.get [1 + 2]")
    elapsed = interp.get("elapsed")
    assert elapsed.kind == "quantity" and elapsed.unit == "ms"
    assert elapsed.value.kind == "floating" and elapsed.value.data >= 0

    # Exercise the upstream source examples for this module, including the
    # object initializer/`this` path and the info display/get variants.
    with open(os.path.join(ROOT, "arturo", "builtin_docs.json"), encoding="utf-8") as fh:
        docs = json.load(fh)
    for name, metadata in docs.items():
        if metadata.get("module") != "Reflection":
            continue
        for index, example in enumerate(metadata.get("examples", [])):
            try:
                Interpreter(out=io.StringIO()).exec(example)
            except Exception as exc:  # pragma: no cover - reported below
                raise AssertionError(f"upstream Reflection example {name}[{index}]: {exc}") from None


def test_system_library_examples() -> None:
    output = io.StringIO()
    Interpreter(out=output, argv=["-c", "-b", "1", "two", "3"]).exec("print args")
    assert output.getvalue() == "[c:true b:true values:[1 two 3]]\n"

    interp = Interpreter(out=io.StringIO())
    interp.exec('result: execute.code "printf hello"')
    result = interp.get("result")
    assert result.data["output"].data == "hello"
    assert result.data["code"].data == 0
    interp.exec('execute.directly.code "exit 7"')

    proc = Interpreter(out=io.StringIO())
    proc.exec("details: process")
    details = proc.get("details")
    assert details.data["id"].data == os.getpid()
    assert details.data["memory"].data["occupied"].unit == "B"


def main() -> int:
    failed = 0
    for source, expected in ALL_CASES:
        try:
            check(source, expected)
            print(f"✓ {source}")
        except AssertionError as exc:
            failed += 1
            print(f"✗ {exc}")
    try:
        test_typed_function_rejects_wrong_argument_type()
        print("✓ typed function rejects an invalid argument type")
        test_arg_returns_runtime_argv()
        print("✓ arg returns runtime argv")
        test_reflection_module_examples()
        print("✓ reflection stack, non-consuming attr?, and benchmark")
        test_system_library_examples()
        print("✓ command-line parsing and system process APIs")
        total = len(ALL_CASES) + 4
    except AssertionError as exc:
        failed += 1
        total = len(ALL_CASES) + 4
        print(f"✗ {exc}")
    print(f"\n{total - failed}/{total} language checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
