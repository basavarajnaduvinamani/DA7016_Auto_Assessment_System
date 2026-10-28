"""Enforce documentation and web signature coverage without importing providers."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/autoassess"


def test_public_python_api_has_docstrings():
    missing = []
    historical = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        documented = [(tree, path.name)]
        documented += [
            (node, node.name)
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        ]
        for node, name in documented:
            doc = ast.get_docstring(node)
            location = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 1)} {name}"
            if not doc:
                missing.append(location)
            elif re.search(r"\b(?:week\s+\d+|task\s+\d+|Codex|Claude)\b", doc, re.I):
                historical.append(location)
    assert not missing, "\n".join(missing)
    assert not historical, "\n".join(historical)


def test_public_web_functions_have_complete_signatures():
    missing = []
    for path in sorted((PACKAGE / "web").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            for arg in arguments:
                if arg.arg not in ("self", "cls") and arg.annotation is None:
                    missing.append(f"{path.name}:{node.name} argument {arg.arg}")
            if node.returns is None:
                missing.append(f"{path.name}:{node.name} return")
    assert not missing, "\n".join(missing)
