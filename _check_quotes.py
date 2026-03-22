import ast

source = ""
try:
    with open("tests/test_logging_config.py") as f:
        source = f.read()
    ast.parse(source)
    print("OK — no syntax errors")
except SyntaxError as e:
    print(f"SyntaxError at line {e.lineno}: {e.msg}")
    # Count triple quotes
    count = source.count('"""')
    print(f"Triple-quote count: {count} (odd={count % 2 == 1})")
    # Show ALL lines with triple quotes
    lines = source.splitlines()
    print("\nLines with triple quotes:")
    for i, line in enumerate(lines):
        if '"""' in line:
            print(f"  Line {i + 1}: {line.rstrip()}")
