#!/usr/bin/env python3
"""Differential smoke test: run small Arturo snippets through the port and the
reference implementation and report where the two disagree.

    $ python3 tools/difftest.py                      # uses `arturo` from PATH
    $ python3 tools/difftest.py --reference /path/to/arturo
    $ python3 tools/difftest.py --only loop map       # only snippets containing a word

Every snippet runs in its own process, so an error in one does not hide the
others.  Differences are classed as:

    MISMATCH   both ran, different output       -> real deviation
    EXTRA      the reference errors, the port works -> the port is more permissive
    MISSING    the port errors, the reference works -> regression / missing feature
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


SNIPPETS = [
    'print 2 * 3 + 4',
    'print 1..5',
    'print map 1..5 => [2 * &]',
    "print map 1..5 'x -> x*2",
    "print select 1..10 'x -> 0 = x % 3",
    "print filter 1..10 'x -> 0 = x % 3",
    "print fold 1..5 'a 'b -> a + b",
    'print sort [3 1 2]',
    'print sort.descending [3 1 2]',
    "print sort.by:'x [[x:3][x:1]]",
    'print pad.center "ab" 6 "*"',
    'print pad.left "ab" 5 "."',
    'print pad.right "ab" 5 "."',
    'print join.with:"-" ["a" "b" "c"]',
    'print split.every:2 1..7',
    'print replace "hello" "l" "L"',
    'print strip "  hi  "',
    'print upper "abc"',
    'print lower "ABC"',
    'print capitalize "abc def"',
    'print reverse "abc"',
    'print reverse [1 2 3]',
    'print unique [1 2 1 3]',
    'print to :string 42',
    'print to :integer "42"',
    'print to :block "abc"',
    'print size "hello"',
    'print first [1 2 3]',
    'print last.n:2 [1 2 3 4]',
    'print contains? "hello" "ell"',
    'print in? 3 [1 2 3]',
    'print keys #[a: 1 b: 2]',
    'print values #[a: 1 b: 2]',
    'print #[a: 1 b: [1 2]]',
    'print @[1 2 3]',
    'print do [1 + 2]',
    'f: $[x][x+1] print f 5',
    'print (1 > 2)? -> "yes" -> "no"',
    'print case [1 = 1 -> "eq"]',
    "print enumerate [10 20 30]",
    'print couple [1 2] [3 4]',
    'print chunk 1..7 3',
    'print digits 1234',
    'print sum digits 1234',
    'print factors 12',
    'print divisors 12',
    'print prime? 97',
    'print gcd 12 18',
    'print lcm 4 6',
    'print round 2.567 2',
    'print sqrt 16',
    'print 2^10',
    'print 10 % 3',
    'print 10 / 3',
    'print 10 // 3',
    'print abs neg 5',
    'print reciprocal 4',
    'print average [1 2 3]',
    'print median [1 5 3]',
    'print variance [1 2 3 4]',
    'print tally ["a" "b" "a"]',
    'print type [1 2]',
    "print type 'a",
    'print to :string.format:"|%05.2f|" 3.14159',
    'print escape "a\\"b"',
    'print empty? ""',
    'print null? ø',
    "print every? [2 4 6] 'x -> 0 = x % 2",
    "print any? [1 2 3] 'x -> 2 < x",
    "print none? [1 2 3] 'x -> 5 < x",
    "print one? [1 2 3] 'x -> 2 = x",
    'print [1 2 3] ++ [4]',
    "xs: [1 2 3] 'xs ++ 4 print xs",
    'print "abc" ++ "def"',
    'print 3 # 4',
    'print shl 1 4',
    'print and? true false',
    "print 2 ∈ [1 2 3]",
    'print 1.5 + 2.25',
    'print 1/2',
    'print 1//2',
    'print to :rational 0.5',
    'print 4 to :complex',
    'print to :string 1.0+2.0i',
    'x: #[a: 1] print x\\a',
    'x: [[1 2] [3 4]] print x\\0\\1',
    'print slice 1..10 2 5',
    'print take 1..10 3',
    'print drop 1..10 3',
    'print repeat "ab" 3',
    'print align.center ["a" "b"]',
    'print join ["a" "b"]',
    'print flatten [[1 2] [3]]',
    'print distinct [1 1 2]',
    'print max [1 5 3]',
    'print min 4 2 8',
    'print sum 1..10',
    'print product 1..5',
    'print (size [1 2]) = 2',
    'print exact? 1.0',
    'print odd? 3',
    'print even? 4',
    'print negative? 0 - 1',
    'print positive? 2',
    'print zero? 0',
    'print between? 5 [1 10]',
    'print compare 1 2',
    'print same? 1 1.0',
    'print equal? "a" "a"',
    'print to :string [1 2 3]',
    'print write.json #[a: 1]',
    'print read.json "{\\"a\\": 1}"',
    'print now\\year = 2026',
    'print to :date "2020-01-02"',
    'print leap? 2024',
    'print days 2024 2',
    'print to :string .format:"YYYY" to :date "2020-01-02"',
    'print sort ["b" "A" "c"]',
    'print sort.sensitive ["b" "A" "c"]',
    'print arrange ["a" "b"] [3 1]',
    'print combine [1 2] [3 4]',
    'print decouple [[1 2] [3 4]]',
    'print couple [[1 2]]',
    'print prefixes "abc"',
    'print suffixes "abc"',
    'print subarray? [1 2] [1 2 3]',
    'print index "abc" "b"',
    'print match "abc" "b"',
    'print split "a,b,c" ","',
    'print split.words "a b  c"',
    'print lines "a\\nb"',
    'print whitespace? " "',
    'print wordwrap "aaa bbb" 3',
    'print truncate "abcdef" 3',
    'print chop "abcdef" 2',
    'print outdent "  a"',
    'print indent "a" 2',
    'print render "{{1+2}}"',
    'print ascii? "a"',
    'print numeric? "12"',
    'print alphabet 3',
    'print crc "abc"',
    'print decode encode "abc"',
    'print digest.sha1 "abc"',
    'print new "abc"',
    'print from.json "[1,2]"',
    'print inspect [1 2]',
    'print prints 1+1',
    'print path "a/b.txt"',
    'print relative "a/b/c"',
    'print exists? "README.md"',
    'print env\\HOME = env\\HOME',
    'print version',
    'print symbol? first [abc]',
    'print literal? \'abc',
    'print label? #abc',
]


def run(cmd, source, timeout=25):
    with tempfile.NamedTemporaryFile("w", suffix=".art", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(source + "\n")
        path = fh.name
    try:
        proc = subprocess.run(cmd + [path], capture_output=True, text=True,
                              timeout=timeout)
        return proc.stdout.strip(), proc.stderr.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        return "", "<timeout>", -1
    finally:
        os.unlink(path)


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", default="arturo",
                    help="path to the reference Arturo binary")
    ap.add_argument("--only", nargs="*", default=None,
                    help="only run snippets containing one of these words")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    port = [sys.executable, "-m", "arturo"]
    cases = [s for s in SNIPPETS
             if not args.only or any(w in s for w in args.only)]

    counts = {"match": 0, "both-error": 0, "MISMATCH": 0, "EXTRA": 0,
              "MISSING": 0}
    for source in cases:
        ref = run(["timeout", "10", args.reference, "--no-color"], source)
        mine = run(port, source)
        ref_ok, port_ok = ref[2] == 0, mine[2] == 0
        if ref_ok and port_ok and ref[0] == mine[0]:
            counts["match"] += 1
            if args.verbose:
                print(f"ok   {source}")
            continue
        if not ref_ok and not port_ok:
            kind = "both-error"     # both reject it (messages may differ)
        elif not ref_ok and port_ok:
            kind = "EXTRA"          # the port accepts what the reference rejects
        elif ref_ok and not port_ok:
            kind = "MISSING"        # regression / not implemented
        else:
            kind = "MISMATCH"
        counts[kind] += 1
        if kind == "both-error" and not args.verbose:
            continue
        print(f"--- {kind}: {source}")
        print(f"    reference: {_short(ref[0])!r} "
              f"rc={ref[2]} {_short(ref[1].splitlines()[-1]) if ref[1] else ''}")
        print(f"    port     : {_short(mine[0])!r} "
              f"rc={mine[2]} {_short(mine[1].splitlines()[-1]) if mine[1] else ''}")

    total = sum(counts.values())
    print()
    agree = counts["match"] + counts["both-error"]
    print(f"{agree}/{total} snippets agree  "
          f"(mismatch {counts['MISMATCH']}, port accepts more "
          f"{counts['EXTRA']}, missing {counts['MISSING']}, "
          f"both reject {counts['both-error']})")
    return 0 if counts["MISMATCH"] == 0 and counts["MISSING"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
