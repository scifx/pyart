# Pyart — Arturo in Python

A from-scratch Python implementation of the [Arturo](https://arturo-lang.io) programming
language: parser, AST builder, evaluator and standard library, plus a benchmark harness
that runs the official Arturo example programs and compares their output against the
`.res` files shipped with the language.

```python
from arturo import Interpreter

Interpreter().exec('print "Hello world!"')
```

```console
$ python3 -m arturo.cli examples/hello.art
Hello world!
```

## What is implemented

The port follows the reference implementation (`arturo-lang/arturo`, Nim) very closely,
module by module:

| Python module | Ported from | Contents |
| --- | --- | --- |
| `arturo/parser.py` | `src/vm/parse.nim` | tokenizer + block parser: symbols, literals, labels, attributes, paths, strings (`«»`, `««»»`, `{...}`, `{:...:}`, `{/regex/}`), numbers, comments |
| `arturo/ast.py` | `src/vm/ast.nim` | arity-driven AST generation: prefix/infix calls, attributes, `->`, `=>`, `::`, `!`, paths, trailing pipes |
| `arturo/evaluator.py` | `src/vm/eval.nim`, `exec.nim` | tree-walking evaluator, scopes/frames, attribute stack, signals (`break`/`continue`/`return`), error values |
| `arturo/values.py` | `src/vm/values/*` | the value hierarchy (integer, floating, rational, logical, block, inline, dictionary, object, range, date, char, string, word, literal, label, path, function, quantity, regex, binary, …) |
| `arturo/library.py` | `src/vm/lib.nim` | symbol table shared by the parser, AST builder and evaluator |
| `arturo/signatures.py` | `src/library/*.nim` | declared arities + accepted attributes for every builtin |
| `arturo/builtins/*.py` | `src/library/*.nim` | Core, Collections, Iterators, Logic, Strings, Numbers, Dates, Files, Reflection, … |
| `arturo/nimtime.py` | `std/times` | date patterns (`yyyy-MM-dd`, `dddd`, …) ⇄ `strftime` |

Language semantics worth pointing out (all verified against the reference runtime):

* **Right-to-left evaluation, no operator precedence**: `2 * 3 + 4` is `14`, `(2 * 3) + 4` is `10`.
* **Arity-driven calls**: a word that names a function consumes exactly as many values as
  the function takes, which is why `print 1 + 2` works without parentheses.
* **Blocks are lazy**, `@[...]` (`array`) and `do` evaluate them; `f: function [x][...]`
  and the `$[x][...]` sugar define functions; `->` wraps the next statement as a block.
* **Attributes** (`.descending`, `.with: ","`) are pushed on a stack that builtins pop.
* **In-place updates** via literals: `'xs ++ 4`, `inc 'i`, `sort 'xs`.
* **`=>` injects implicit parameters** (`&`, `__`, …) into a block.
* `if?`/`else` (0.9 style, used by the examples corpus), `when`, `switch`, `while`, `until`.

## Running the tests

```console
$ python3 tests/test_language.py        # 85 language-level checks
$ python3 -m pytest tests -q            # same, through pytest
```

## Benchmarks

`benchmarks/examples/` contains the upstream Arturo examples (668 `.art` files, 488 of
them with an expected-output `.res` file). Only the ones the reference runtime itself
passes are scored (338 files, see `benchmarks/reference_pass.json`).

```console
$ python3 benchmarks/run_examples.py --jobs 8          # score
$ python3 benchmarks/run_examples.py --show-fail 30    # + worst offenders
$ python3 benchmarks/one.py "100 doors"                # debug a single example
```

See `benchmarks/README.md` for details.

## Notes / limitations

* Work in progress: not every builtin is implemented yet (see the score above) and some
  builtins fall back to a "Not Implemented" error.
* Strings are immutable Python objects, so the reference-implementation nicety that two
  variables pointing at the same string see each other's in-place updates does not hold.
* Performance is that of a tree-walking interpreter in Python.
