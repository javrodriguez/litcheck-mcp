"""The core stays Python 3.6 grammar and standard library only.

GARS vendors this core onto a cluster whose python3 is 3.6.8, so a newer
construct is a break, not a style choice. ast.parse with feature_version
catches most of them; the visitor below catches what it lets through.
"""
import ast
import os
import sys
import unittest

from tests import CORE

PACKAGE = os.path.join(CORE, 'litcheck')
TOOLS = os.path.join(CORE, 'tools')

# Top-level modules the core may import. Anything else is a dependency.
STDLIB = {
    'argparse', 'datetime', 'email', 'fcntl', 'hashlib', 'json', 'ntpath', 'os', 're', 'sys',
    'threading', 'time', 'unicodedata', 'urllib',
}
BANNED_MODULES = {'dataclasses', 'typing', 'contextvars', 'zoneinfo', 'graphlib', 'tomllib'}
BANNED_CALLS = {'removeprefix', 'removesuffix', 'isascii', 'fromisoformat'}
BANNED_ATTRIBUTES = {'UTC'}  # datetime.UTC is 3.11


def sources():
    out = []
    for folder in (PACKAGE, TOOLS):
        for name in sorted(os.listdir(folder)):
            if name.endswith('.py'):
                out.append(os.path.join(folder, name))
    return out


class Visitor(ast.NodeVisitor):
    def __init__(self):
        self.problems = []
        self.imports = set()

    def bad(self, node, what):
        self.problems.append('line %s: %s' % (getattr(node, 'lineno', '?'), what))

    def visit_ImportFrom(self, node):
        if node.module == '__future__' and any(a.name == 'annotations' for a in node.names):
            self.bad(node, 'from __future__ import annotations')
        if node.level == 0 and node.module:
            self.imports.add(node.module.split('.')[0])
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self.bad(node, 'walrus operator')

    def visit_Match(self, node):
        self.bad(node, 'match statement')

    def visit_arguments(self, node):
        if getattr(node, 'posonlyargs', None):
            self.bad(node, 'positional-only parameters')
        self.generic_visit(node)

    def visit_JoinedStr(self, node):
        self.bad(node, 'f-string (use % formatting; 3.8 added f"{x=}")')

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_CALLS:
            self.bad(node, 'call to .%s()' % node.func.attr)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in BANNED_ATTRIBUTES:
            self.bad(node, '.%s' % node.attr)
        self.generic_visit(node)

    def _annotation(self, node, annotation):
        if annotation is None:
            return
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) \
                    and sub.value.id in ('list', 'dict', 'set', 'tuple', 'type', 'frozenset'):
                self.bad(node, 'builtin-subscript annotation %s[...]' % sub.value.id)
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                self.bad(node, 'X | Y annotation')

    def visit_FunctionDef(self, node):
        self._annotation(node, node.returns)
        for arg in node.args.args + node.args.kwonlyargs:
            self._annotation(node, arg.annotation)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_AnnAssign(self, node):
        self._annotation(node, node.annotation)
        self.generic_visit(node)


class CompatTests(unittest.TestCase):
    def test_sources_found(self):
        names = [os.path.basename(p) for p in sources()]
        # guard the guard: an empty sweep would pass every test below
        for expected in ('__init__.py', 'transport.py', 'ids.py', 'record_fixture.py'):
            self.assertIn(expected, names)
        self.assertEqual(len(names), len(set(names)))

    def test_parses_as_python_36(self):
        for path in sources():
            with open(path, encoding='utf-8') as handle:
                source = handle.read()
            if sys.version_info >= (3, 8):
                ast.parse(source, filename=path, feature_version=(3, 6))
            else:
                ast.parse(source, filename=path)

    def test_no_newer_constructs(self):
        for path in sources():
            with open(path, encoding='utf-8') as handle:
                visitor = Visitor()
                visitor.visit(ast.parse(handle.read(), filename=path))
            self.assertEqual(visitor.problems, [], path)

    def test_imports_are_stdlib_allowlist(self):
        for path in sources():
            with open(path, encoding='utf-8') as handle:
                visitor = Visitor()
                visitor.visit(ast.parse(handle.read(), filename=path))
            extra = visitor.imports - STDLIB - {'litcheck'}
            self.assertEqual(extra, set(), '%s imports %s' % (path, sorted(extra)))
            self.assertEqual(visitor.imports & BANNED_MODULES, set(), path)

    def test_package_uses_relative_imports(self):
        for path in sources():
            if not path.startswith(PACKAGE):
                continue
            with open(path, encoding='utf-8') as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotEqual((node.module or '').split('.')[0], 'litcheck', path)

    def test_visitor_catches_what_it_claims(self):
        samples = {
            'from __future__ import annotations\n': 'annotations',
            'def f(x: list[int]): pass\n': 'builtin-subscript',
            'def f(x: int | None): pass\n': 'X | Y',
            'x = "a".removeprefix("b")\n': 'removeprefix',
            'import datetime\nx = datetime.UTC\n': '.UTC',
            'x = 1\ny = f"{x}"\n': 'f-string',
        }
        if sys.version_info >= (3, 8):  # newer syntax only parses on a newer interpreter
            samples['if (y := 1): pass\n'] = 'walrus'
            samples['def f(a, /, b): pass\n'] = 'positional-only'
            samples['x = 1\ny = f"{x=}"\n'] = 'f-string'
        if sys.version_info >= (3, 10):
            samples['match x:\n    case 1: pass\n'] = 'match'
        for source, expected in samples.items():
            visitor = Visitor()
            visitor.visit(ast.parse(source))
            self.assertTrue(any(expected in p for p in visitor.problems), source)


if __name__ == '__main__':
    unittest.main()
