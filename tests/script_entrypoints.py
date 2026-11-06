"""Load isolated QA script entry functions without starting their CLI runtime."""

import ast
from pathlib import Path


def script_function(path: str, name: str, **overrides):
    """Compile a single script function with explicitly supplied dependencies."""
    source = Path(__file__).resolve().parents[1] / path
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    node = next(node for node in tree.body if (
        isinstance(node, ast.AsyncFunctionDef) and node.name == name
    ))
    node.decorator_list = []
    namespace = dict(overrides)
    namespace.setdefault("__builtins__", __builtins__)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]
