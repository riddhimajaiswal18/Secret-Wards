"""The repository must not advertise capabilities it does not have.

Any module under src/ that nothing imports is either dead code or a placeholder pretending to be a
feature (21 such modules were found in the Phase 0 audit: linkage/, pseudonymization/, privacy/).
This test makes that state impossible to reintroduce silently: a module must be imported, be a
package __init__, or be declared in config/capabilities.json.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DECLARED = json.loads((ROOT / "config" / "capabilities.json").read_text())["not_implemented"]
# Modules deliberately invoked as `python -m src.…` rather than imported (CLI entry points).
ENTRY_POINTS = {"src.ingestion.parse_file"}


def _modules() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _imported_everywhere() -> set[str]:
    """Every module named by an import statement anywhere in the project (AST, not text search)."""
    names: set[str] = set()
    sources = (list(SRC.rglob("*.py")) + list((ROOT / "tools").rglob("*.py"))
               + list((ROOT / "tests").rglob("*.py")) + [ROOT / "main.py"])
    for path in sources:
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        here = list(path.relative_to(ROOT).with_suffix("").parts)
        package = here[:-1]                       # directory of this module, as a package path
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:                     # relative import: resolve against this package
                    base = package[:len(package) - (node.level - 1)] if node.level > 1 else package
                    module = ".".join([*base, *( [node.module] if node.module else [])])
                else:
                    module = node.module or ""
                if not module:
                    continue
                names.add(module)
                names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_every_module_is_imported_or_declared():
    imported = _imported_everywhere()
    orphans = []
    for path in _modules():
        if path.name == "__init__.py":
            continue
        dotted = str(path.relative_to(ROOT).with_suffix("")).replace("/", ".")
        package = dotted.rsplit(".", 1)[0]
        if dotted in imported or dotted in ENTRY_POINTS:
            continue
        if package in imported and f"{package}.{path.stem}" in imported:
            continue
        orphans.append(dotted)
    assert not orphans, (
        "modules neither imported nor declared in config/capabilities.json: "
        + ", ".join(sorted(orphans)))


def test_no_one_line_stub_in_src():
    stubs = [str(p.relative_to(ROOT)) for p in _modules()
             if len(p.read_text(encoding="utf-8", errors="ignore").strip().splitlines()) <= 1
             and p.name != "__init__.py"]
    assert not stubs, "placeholder modules in src/: " + ", ".join(stubs)


def test_declared_capabilities_are_not_in_src():
    """A capability declared not_implemented must not also exist as a module (no double truth)."""
    present = []
    for name in DECLARED:
        if (SRC / (name.replace(".", "/") + ".py")).exists():
            present.append(name)
    assert not present, "declared not_implemented but present in src/: " + ", ".join(present)
