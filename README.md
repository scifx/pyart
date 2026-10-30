# Pyart — Arturo in Python

A from-scratch Python implementation of the [Arturo](https://arturo-lang.io) programming
language: tokenizer, parser, arity-driven AST builder, tree-walking evaluator, value
system and a large part of the standard library.

The port is developed **against the reference implementation**
([`arturo-lang/arturo`](https://github.com/arturo-lang/arturo), written in Nim,
`0.10.1-dev`) and is validated by running the real Arturo example corpus and comparing
the output byte for byte.

```console
$ python3 -m arturo -e 'print "Hello world!"'
Hello world!
```

| | |
| --- | --- |
| Example benchmark | **337 / 338 (99.7 %)** of the examples the reference runtime passes |
| Language tests | **85 / 85** (`tests/test_language.py`, every check cross-checked with the reference binary) |
| Builtin library | **334 implemented** of 551 registered names (217 still stubs, see [`docs/BUILTIN_STATUS.md`](docs/BUILTIN_STATUS.md)) |
| Code size | ~9.3k lines of Python |
| Main remaining blocker | interpreter **speed** (a few compute-heavy examples need 20–50 s) |

---

## Quick start

No packaging step is required — run from the repository root (Python 3.9+).

```console
$ python3 -m arturo path/to/script.art      # run a file
$ python3 -m arturo -e 'print 2 * 3 + 4'    # evaluate a snippet  -> 14
$ python3 -m arturo                         # interactive REPL
```

Embedding it:

```python
from arturo import Interpreter

interp = Interpreter()
interp.exec('x: [1 2 3]')
print(interp.exec('size x').data)    # 3   (exec returns the last value)
print(interp.get('x'))               # <Block [1 2 3]>  (a variable)
interp.exec_file('script.art')
```

`Interpreter(out=..., argv=[...])` lets you capture output and set the program
arguments (`args`, `script`).

---

## Project layout

| Python module | Ported from | Contents |
| --- | --- | --- |
| `arturo/parser.py` | `src/vm/parse.nim` | tokenizer + block parser: symbols, literals, labels, attributes, paths, strings (`"…"`, `«…`, `««…»»`, `{…}`, `{:…:}`, `{/regex/}`, `---…---`, `~"…|code|…"`), numbers, comments |
| `arturo/ast.py` | `src/vm/ast.nim` | arity-driven AST generation: prefix/infix calls, attribute stacking, `->`, `=>`, `::`, `!`, paths, pipes; also the **compiled fast paths** (`Node.fast`) |
| `arturo/evaluator.py` | `src/vm/eval.nim`, `exec.nim` | tree-walking evaluator, scopes/frames, attribute stack, signals (`break`/`continue`/`return`/`ensure`), collectors, error values |
| `arturo/values.py` | `src/vm/values/*` | value hierarchy (integer, floating, rational, complex, logical, quantity, char, string, block, inline, dictionary, object, range, date, binary, function, iterator, …), printing/formatting, comparison |
| `arturo/library.py` | `src/vm/lib.nim` | symbol table shared by parser, AST builder and evaluator |
| `arturo/signatures.py` | `src/library/*.nim` | **523** declared arities + accepted attributes (drives parsing of every call) |
| `arturo/builtins/*.py` | `src/library/*.nim` | the standard library: `core`, `collections`, `strings`, `iterators`, `numbers`, `misc`, `dates` |
| `arturo/nimtime.py` | `std/times` | date pattern handling (`yyyy-MM-dd`, `dddd`, …) |
| `arturo/cli.py`, `repl.py` | `src/arturo.nim` | command line entry point and REPL |
| `tools/inventory.py` | — | regenerates the implemented/stub inventory in `docs/` |
| `tests/test_language.py` | — | 85 language-level checks |
| `benchmarks/` | — | harness that runs the upstream examples and diffs their output |

### Language semantics that are implemented 1:1

* **Right-to-left evaluation, no operator precedence** — `2 * 3 + 4` is `14`,
  `(2 * 3) + 4` is `10`.
* **Arity-driven calls** — a word that names a function consumes exactly as many values
  as the function takes, which is why `print 1 + 2` needs no parentheses.
* **Blocks are lazy**; `@[…]` (`array`) and `do` evaluate them.
* **Attributes** (`.descending`, `.with: ","`) live on a stack that builtins pop;
  `.attr` / `.attr?` / `.attrs` behave differently.
* **Scoping** — blocks have no scope, functions isolate (with `.inline` running in the
  caller's scope), iterators restore the variables they inject.
* **Values are references** — `a: [1 2]; b: a; 'b ++ 3` makes `a` grow too; `new`
  copies. String literals are detached on assignment so the same rules hold for them.
* **In-place updates via literals** — `'xs ++ 4`, `inc 'i`, `sort 'xs`, `d\key: v`.
* **`=>` injects implicit parameters** (`&`, `__`) into a block; `->` wraps the next
  statement as a single-value block.
* `if`/`if?`/`else`, `when`/`when?`, `switch`/`switch?`, `case`, `unless`/`unless?`,
  `while`, `until`, `try`/`throw`/`panic`/`ensure`, `loop`/`map`/`select`/`filter`/
  `fold`/`collect`/`arrange`, `return`/`break`/`continue`.

---

## Benchmarks

`benchmarks/examples/` contains the upstream Arturo examples (668 `.art` files, 488 of
them with an expected `.res` file). Only the examples that the **reference runtime
itself passes** are scored — 338 files, listed in `benchmarks/reference_pass.json`.

```console
$ python3 benchmarks/run_examples.py --jobs 2 --timeout 60   # full run (~40 min on 2 CPUs)
$ python3 benchmarks/run_examples.py --jobs 8 --timeout 60   # faster on a bigger box
$ python3 benchmarks/one.py "100 doors"                      # debug one example
$ python3 benchmarks/run_examples.py --show-fail 30          # + worst offenders
```

Current result of a full run (`--jobs 2 --timeout 60`, `/tmp/b23.json`):

```
passed 337/338 examples (99.7%)
plus 42 examples the reference runtime itself cannot run
```

The single failure is `rosetta/perfect numbers.art`: it takes ~41 s standalone and runs
past the 60 s timeout when two examples share the two CPUs. With the harness default
`--timeout 20` these compute-heavy examples also go over budget (all of them pass at
60 s):

| example | time |
| --- | ---: |
| `perfect numbers` | > 60 s (41 s standalone) |
| `curzon numbers` | 50 s |
| `permutations - derangements` | 36 s |
| `changeable words` | 35 s |
| `abundant odd numbers` | 22 s |
| `truncatable primes` | 20 s |
| `circular primes` | 14 s |
| `ascending primes` | 12 s |

Everything else finishes in well under 10 s. The gap is pure interpreter speed, not
correctness — see the roadmap below.

---

## Standard library coverage

`arturo/signatures.py` knows every name the reference library declares (551 of them), so
parsing and arity handling are complete even for builtins that are not implemented yet.
An unimplemented builtin raises `Not Implemented`, which makes the gaps obvious instead
of silently producing wrong results.

| module | implemented |
| --- | ---: |
| `core.py` — control flow, logic, conversion, reflection, bitwise | 128 |
| `numbers.py` — arithmetic, primes, clamps, statistics, random | 58 |
| `collections.py` — blocks, dictionaries, sets, sorting, paths | 52 |
| `strings.py` — splitting, padding, formatting, regex, encoding | 32 |
| `misc.py` — files, paths, JSON, IO, crypto digests, system info | 30 |
| `iterators.py` — `loop`/`map`/`select`/`filter`/`fold`/`combine`/… | 23 |
| `dates.py` — `now`, `today`, date arithmetic and predicates | 11 |
| *(declared only — stubs)* | 217 |

**Full list**: [`docs/BUILTIN_STATUS.md`](docs/BUILTIN_STATUS.md) (regenerate with
`python3 tools/inventory.py --markdown > docs/BUILTIN_STATUS.md`).

### What is *not* implemented yet (217 names)

* **Quantity-type predicates (60)** — `length?`, `mass?`, `area?`, `pressure?`,
  `temperature?`, … These only need a unit-family table, so they are cheap to add.
* **Translated aliases (42)** — the Chinese keyword set (`如果`, `循环`, `打印`, `映射`,
  `筛选`, …). Pure aliasing of builtins that already exist.
* **Everything else (115)** — three groups worth distinguishing:
  * *cheap reflection / small helpers*: `info`, `methods`, `arg`, `eval`, `parse`,
    `hash`, `in`, `units`, `sortable`, `conforms?`, `with`, `set?`, `iterator`,
    `entropy?`, `errorKind?`, `hidden?`, `superuser?`.
  * *OS / filesystem*: `cd`, `execute`, `process`, `permissions`, `rename`, `symlink`,
    `terminal`, `pause`, `wait`, `open`/`close`/`seek`/`tell`/`rewind`.
  * *system-level subsystems* (largest effort): `net` (`serve`, `request`, `download`,
    `mail`, `socket?`), `ui` (`webview`, `dialog`, `popup`, `alert`, colour helpers),
    `db` (`database?`, `query`), tasks/fibers (`yield`, `channel`, `terminate`,
    `cancel`, `send`/`receive`), bytecode (`store`, `peek`, `goto`, `discard`).

---

## Extending the library (hot-plugging builtins)

Adding a builtin is a 5-line change in **one** file — the registry is global, and arity +
attributes are registered with it, so the parser immediately knows how many values the
new word consumes:

```python
# arturo/builtins/numbers.py
from . import builtin, impl, inplace, attr, attr_true, fail, to_int, to_number
from .. import values as V

@builtin("half", arity=1)                     # a brand new builtin
def _half(ev, args):
    return V.Floating(to_number(args[0]) / 2)
```

```console
$ python3 -m arturo -e 'print half 5'
2.5
```

Real example — `clamp` (already implemented this way):

```python
@impl("clamp")
def _clamp(ev, args):
    value, bounds = args[0], args[1]          # clamp 42 1..10  =>  10
    ...
```

* `@builtin(name, arity, attrs=[...])` declares a new builtin **and** its call arity;
  `@impl(name)` attaches/replaces the Python body of a builtin that `signatures.py`
  already declares.
* Handlers get `(ev, args) -> Value`; `ev` exposes `ev.ctx` (symbol table, attribute
  stack, `ev.ctx.out`), `ev.do_block(block)`, `ev.inplace_target(literal)`.
* Anything declared in `signatures.py` but without an implementation is installed as a
  stub, so the port can be filled in incrementally without touching the parser.
* Runtime-level aliasing is supported too (`alias.infix`, `DYNAMIC_INFIX`), and users can
  define their own functions (`f: function [x][…]`, `$[x][…]`, `.memoize`, `.import`).

---

## Development workflow

```console
$ python3 tests/test_language.py              # 85 language checks (fast)
$ python3 benchmarks/one.py "bead sort"       # run one example + diff with the .res
$ python3 tools/inventory.py                  # builtin coverage report
$ python3 tools/difftest.py --reference /path/to/arturo   # differential smoke test
```

When behaviour is unclear, the reference binary is the source of truth:

```console
$ arturo --no-color probe.art                 # reference implementation
$ python3 -m arturo probe.art                 # the port
```

A good habit while porting: write the snippet to a file (the reference implementation
parses `-e` differently), run both, and diff.

### Performance notes

The interpreter evaluates the AST with compiled closures: `ast._compile_node` attaches a
`Node.fast` callable to constants, variables, simple calls and single-child stores, and
specialises integer arithmetic/comparison (`_INT_SPEC`) so that tight loops such as
`select 1..n 'i -> 0 = n % i` avoid the generic dispatch path. Frozen literals are thawed
on *store* (not on every evaluation). Typical cost is ~1.5–2 µs per interpreted loop
iteration, 20–50× slower than the compiled Nim runtime — which is exactly why the
handful of heavy examples above are borderline.

---

## Known deviations from the reference implementation

Everything below was found with `tools/difftest.py` (157 snippets run through both
`arturo --no-color` and `python3 -m arturo`): **138 agree, 15 are cases where the port
accepts more than the reference, 22 are rejected by both, 3 genuinely differ**:

| area | deviation |
| --- | --- |
| `->` arrow bodies | only the *next statement* is captured — the parser has no newline/indentation information, so a multi-line chain after `->` is grouped differently than in Arturo |
| date arithmetic | `date - date` raises `Type Error: cannot subtract date from date`; the reference returns a `:duration` |
| `truncate` | the reference keeps the string unchanged in a few cutoff/filler edge cases where the port truncates |
| `digest.sha1` | the reference only documents `.sha`; `.sha1`/`.sha256`/`.md5` are honoured by the port (superset) |
| `path "file"` | the reference's `path` takes no arguments; the port additionally returns file info for a path (superset) |
| permissive extras | `slice`/`drop` on ranges, `to :date` from a plain string, variadic `min`/`max`, `distinct`, `none?` — accepted by the port, rejected by the reference |
| tasks / threads | `.async`, `.parallel`, fiber-based helpers are accepted attribute-wise but not executed concurrently |
| `inspect` | returns the formatted string; the reference prints it as a side effect (and prints a slightly different layout for dictionaries) |

---

## Roadmap (highest value first)

1. **Speed**: compile single-statement loop bodies (`select`/`map`/`loop`) into integer
   expressions — target ~0.3 µs/iteration, which puts every example comfortably under
   the 20 s budget.
2. **Cheap builtins**: the 60 quantity predicates and the 42 translated aliases (both
   mechanical), plus the remaining small helpers (`info`, `methods`, `arg`, `eval`,
   `parse`, `hash`, `in`, `units`, `conforms?`, `set?`, …).
3. **Semantic polish**: multi-line `->` capture (needs newline-aware parsing),
   `date - date` → `:duration`, `truncate`/`sample.size` edge cases. Also the
   `same?`/`type` corners.
4. **Subsystems**: filesystem mutation (`rename`, `symlink`, `permissions`), process
   execution, sockets/HTTP, sqlite, tasks/fibers, UI.
