"""Find functions returning dicts without return type annotations."""
import ast
import os

DIRS = ['analysis', 'constitution', 'core', 'pipeline']
findings = []

def returns_dict(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            val = child.value
            if isinstance(val, ast.Dict):
                return True
            if isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == 'dict':
                return True
            if isinstance(val, ast.DictComp):
                return True
    return False

def has_return_annotation(node):
    return node.returns is not None

for d in DIRS:
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != '__pycache__' and x != 'tests']
        if 'test' in root:
            continue
        for f in files:
            if not f.endswith('.py'):
                continue
            filepath = os.path.join(root, f)
            try:
                with open(filepath, encoding='utf-8') as fh:
                    source = fh.read()
                source_lines = source.splitlines()
                tree = ast.parse(source)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):  # noqa: SIM102
                    if returns_dict(node) and not has_return_annotation(node):
                        lineno = node.lineno
                        line = source_lines[lineno - 1].rstrip()
                        full_def = line
                        idx = lineno
                        paren_count = full_def.count('(') - full_def.count(')')
                        while paren_count > 0 and idx < len(source_lines):
                            idx += 1
                            next_line = source_lines[idx - 1].strip()
                            full_def += ' ' + next_line
                            paren_count += next_line.count('(') - next_line.count(')')
                            if len(full_def) > 400:
                                break

                        class_name = ''
                        for parent in ast.walk(tree):
                            if isinstance(parent, ast.ClassDef):
                                for item in parent.body:
                                    if item is node:
                                        class_name = parent.name

                        abs_path = os.path.abspath(filepath)
                        findings.append({
                            'file': abs_path,
                            'line': lineno,
                            'name': node.name,
                            'cls': class_name,
                            'def_line': full_def.strip(),
                        })

findings.sort(key=lambda x: (x['file'], x['line']))

for f in findings:
    kind = 'method' if f['cls'] else 'function'
    cls_label = f" [{f['cls']}]" if f['cls'] else ''
    print(f"FILE: {f['file']}")
    print(f"LINE: {f['line']}")
    print(f"TYPE: ({kind}){cls_label}")
    print(f"SIG:  {f['def_line']}")
    print("FIX:  -> dict[str, Any]")
    print('---')

print(f"\nTotal findings: {len(findings)}")
