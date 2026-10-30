# Benchmark harness

Runs the upstream Arturo example programs (`examples/` from Arturo `0.9.83`) through the
Python port and compares the output with the `.res` files.

## Usage

```console
python3 benchmarks/run_examples.py                 # score against the reference set
python3 benchmarks/run_examples.py --show-fail 30  # print the first 30 failures
python3 benchmarks/run_examples.py --jobs 8 --json /tmp/out.json
python3 benchmarks/run_examples.py --all           # score every example with a .res
python3 benchmarks/one.py "100 doors"              # run + show diff for one example
```

* Each example runs in a **subprocess** (`--single <path>`) with a timeout, so a hanging
  example cannot take the whole run down. `--jobs` controls the thread pool size.
* Failures are reported in three flavours: `error: <kind>` (the port raised), `diff`
  (output differs from the expectation) and `timeout`.
* Output comparison is whitespace-normalised per line (trailing spaces stripped) because
  several `.res` files disagree with the reference runtime about trailing spaces.

## Why `reference_pass.json`?

Some `.res` files are stale: the reference runtime (`bin/arturo`, `0.10.1-dev`) itself
does not produce them. Scoring against files nobody can reproduce would be meaningless,
so the harness only counts examples the reference passes. Regenerate the list with:

```console
python3 benchmarks/run_examples.py --reference /path/to/arturo
```

(that writes `reference_pass.json` after running every example with the real runtime).

## Corpus

* `examples/` — copied from the Arturo `0.9.83` release tarball (examples + expected
  output + data files such as `unixdict.txt`).
* `_drafts/` — work-in-progress examples, several of which need network access.
