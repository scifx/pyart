"""Run a series of real-world Arturo examples to verify the implementation."""
import io
import sys
import traceback
from contextlib import redirect_stdout

sys.path.insert(0, '/home/user/arturo_mini')
from arturo_mini.arturo import Interpreter


def run(name, src, expected=None):
    buf = io.StringIO()
    interp = Interpreter()
    err = None
    try:
        with redirect_stdout(buf):
            interp.exec(src)
    except Exception as e:
        err = traceback.format_exc()
    actual = buf.getvalue().rstrip("\n")
    if expected is not None:
        if actual == expected:
            print(f"✓ {name}")
            return True
        else:
            print(f"✗ {name}")
            print(f"  expected: {expected!r}")
            print(f"  actual:   {actual!r}")
            if err:
                print(f"  error: {err}")
            return False
    else:
        if err:
            print(f"✗ {name} (error)")
            print(f"  error: {err}")
            return False
        print(f"? {name}")
        print(f"  output: {actual!r}")
        return True


# 1. Hello world
run("hello", 'print "Hello world!"', "Hello world!")

# 2. Variables and arithmetic
run("vars", '''
a: 2
b: 3
print a + b
print a * b
''', ["5", "6"])

# 3. Functions
run("factorial", '''
factorial: function [n][
    if n <= 1 -> return 1
    n * factorial n-1
]
print factorial 5
''', "120")

# 4. Fibonacci
run("fibonacci", '''
fib: function [n][
    switch n < 2 [
        return n
    ][
        return fib n-1 + fib n-2
    ]
]
loop 1..10 'i [
    print fib i
]
''', ["1", "1", "2", "3", "5", "8", "13", "21", "34", "55"])

# 5. FizzBuzz
run("fizzbuzz", '''
loop 1..15 'n [
    switch n % 15 = 0 [
        print "FizzBuzz"
    ][
        switch n % 3 = 0 [
            print "Fizz"
        ][
            switch n % 5 = 0 [
                print "Buzz"
            ][
                print n
            ]
        ]
    ]
]
''', ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz", "11", "Fizz", "13", "14", "FizzBuzz"])

# 6. Map/filter/reduce
run("mapfilter", '''
print size [1 2 3 4 5]
print sum [1 2 3 4 5]
print maximum [1 5 3 2 4]
print minimum [1 5 3 2 4]
print sort.descending [1 5 3 2 4]
''', ["5", "15", "5", "1", "5 4 3 2 1"])

# 7. String operations
run("strings", '''
print contains? "hello" "ell"
print startsWith "hello" "he"
print endsWith "hello" "lo"
print replace "hello" "l" "L"
print repeat "ab" 3
print pad "hi" 5
''', ["true", "true", "true", "heLLo", "ababab", "hi   "])

# 8. While and break
run("whilebreak", '''
i: 0
while true [
    if i >= 5 -> break
    print i
    inc 'i
]
''', ["0", "1", "2", "3", "4"])

# 9. Dictionary
run("dict", '''
d: #[name: "Alice", age: 30]
print d
print d\\name
print d\\age
d\\city: "NYC"
print d\\city
''', ['#[name: "Alice" age: 30]', "Alice", "30", "NYC"])

# 10. Range and iteration
run("range", '''
loop 1..5 'i -> print i * i
''', ["1", "4", "9", "16"])

# 11. Logical ops
run("logical", '''
print true and false
print true or false
print not false
print true xor false
''', ["false", "true", "true", "true"])

# 12. Math
run("math", '''
print sqrt 16
print abs neg 5
print pi
print 2 ^ 10
''', ["4", "5", "3.141592653589793", "1024"])

print("\nDone.")
