"""CI gate: no new ``gigaevo_memory`` imports in production code (iter #44).

The package was renamed to ``gigaevo_client`` in 0.3.0. The legacy
``gigaevo_memory`` import path still works via the shim that fires a
:class:`DeprecationWarning`, but production code should use the
canonical name so the warning never surfaces in CI.

This test walks the production directories listed in ``PROD_DIRS``
and fails if any Python file contains a top-level executable
``from gigaevo_memory ...`` or ``import gigaevo_memory ...`` line.

Excluded paths:

* The legacy shim itself (``client/python-meta/src/gigaevo_memory/``).
* Test directories (``api/tests/``, ``client/python/tests/``).
  Tests intentionally exercise the legacy path to verify the shim
  emits the deprecation warning and forwards correctly.

Negative-path coverage: ``test_gate_catches_synthetic_violation``
writes a temp file with a forbidden import and runs the same scanner
against it to confirm the gate would fire on a real regression.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

#: Directories that ship to production (excluding test trees and the
#: legacy shim). ``gigaevo_client/`` is the canonical SDK source —
#: it should never import from the legacy name.
PROD_DIRS: tuple[str, ...] = (
    "api/app",
    "web_ui/app",
    "client/python/src/gigaevo_client",
)


def _is_legacy(module_name: str | None) -> bool:
    """True iff a module name refers to the legacy ``gigaevo_memory``
    package or one of its submodules. ``gigaevo_memory_something``
    is fine (different name)."""
    if module_name is None:
        return False
    return module_name == "gigaevo_memory" or module_name.startswith(
        "gigaevo_memory."
    )


def _scan(path: pathlib.Path) -> list[tuple[pathlib.Path, int, str]]:
    """Return every legacy-import statement found in ``.py`` files
    under ``path``. Uses AST so docstring text and comment mentions
    of ``gigaevo_memory`` don't trigger false positives. Each hit is
    ``(file, line_no, rendered_statement)``."""
    hits: list[tuple[pathlib.Path, int, str]] = []
    for py in path.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(py))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if _is_legacy(node.module):
                    hits.append(
                        (py, node.lineno, f"from {node.module} import ...")
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_legacy(alias.name):
                        hits.append(
                            (py, node.lineno, f"import {alias.name}")
                        )
    return hits


# ---------------------------------------------------------------------------
# Positive path: production tree is clean
# ---------------------------------------------------------------------------


class TestProductionTreeClean:
    def test_no_legacy_imports_in_any_prod_dir(self):
        """Walk every prod directory; collect every legacy import;
        fail with a list so all violations surface in one run."""
        all_hits: list[tuple[pathlib.Path, int, str]] = []
        for sub in PROD_DIRS:
            d = REPO_ROOT / sub
            if not d.exists():  # tolerate missing dirs in lean checkouts
                continue
            all_hits.extend(_scan(d))

        if all_hits:
            lines = "\n".join(
                f"  {p.relative_to(REPO_ROOT)}:{n}  {line!r}"
                for p, n, line in all_hits
            )
            raise AssertionError(
                "Legacy 'gigaevo_memory' imports found in production "
                "code. Replace with 'gigaevo_client' — the legacy "
                "shim is for backward-compat only and emits a "
                "DeprecationWarning at runtime.\n\n" + lines
            )

    def test_canonical_package_self_consistent(self):
        """The canonical ``gigaevo_client`` package must never import
        from the legacy name — circular shim → infinite warning."""
        d = REPO_ROOT / "client" / "python" / "src" / "gigaevo_client"
        if not d.exists():
            return
        hits = _scan(d)
        assert hits == [], (
            "gigaevo_client/ contains gigaevo_memory imports: "
            f"{[(str(h[0].relative_to(REPO_ROOT)), h[1]) for h in hits]}"
        )

    def test_web_ui_migrated(self):
        """``web_ui/app/client.py`` was the first downstream caller
        migrated in iter #44; smoke-check the file is clean."""
        target = REPO_ROOT / "web_ui" / "app" / "client.py"
        if not target.exists():
            return
        hits = _scan(target.parent)
        target_hits = [h for h in hits if h[0] == target]
        assert target_hits == [], (
            f"web_ui/app/client.py still imports gigaevo_memory: "
            f"{target_hits}"
        )


# ---------------------------------------------------------------------------
# Negative path: confirm the gate would catch a regression
# ---------------------------------------------------------------------------


class TestGateNegativePath:
    def test_gate_catches_synthetic_from_import(self, tmp_path):
        py = tmp_path / "fake.py"
        py.write_text(
            "from gigaevo_memory import MemoryClient\n"
            "client = MemoryClient()\n"
        )
        hits = _scan(tmp_path)
        assert len(hits) == 1
        assert hits[0][1] == 1  # line number
        assert "gigaevo_memory" in hits[0][2]

    def test_gate_catches_bare_import(self, tmp_path):
        py = tmp_path / "fake.py"
        py.write_text("import gigaevo_memory\n")
        hits = _scan(tmp_path)
        assert len(hits) == 1

    def test_gate_catches_aliased_import(self, tmp_path):
        py = tmp_path / "fake.py"
        py.write_text("import gigaevo_memory as gm\n")
        hits = _scan(tmp_path)
        assert len(hits) == 1

    def test_gate_catches_submodule_import(self, tmp_path):
        py = tmp_path / "fake.py"
        py.write_text("from gigaevo_memory.config import GigaEvoConfig\n")
        hits = _scan(tmp_path)
        assert len(hits) == 1

    def test_gate_catches_imports_inside_functions(self, tmp_path):
        """Imports inside function bodies are still flagged — production
        code mustn't reach for the legacy path at any depth."""
        py = tmp_path / "fake.py"
        py.write_text(
            "def f():\n"
            "    from gigaevo_memory import X\n"
            "    return X\n"
        )
        hits = _scan(tmp_path)
        assert len(hits) == 1
        assert hits[0][1] == 2  # the indented import line

    def test_gate_ignores_docstring_mentions(self, tmp_path):
        """A docstring or comment mentioning ``gigaevo_memory`` is fine
        — only executable import statements count."""
        py = tmp_path / "fake.py"
        py.write_text(
            '"""Module that used to live in gigaevo_memory."""\n'
            "# legacy path: gigaevo_memory.MemoryClient\n"
            "text = 'gigaevo_memory'\n"
            "def f():\n"
            '    """\n'
            "    Usage::\n"
            "        from gigaevo_memory import X\n"
            '    """\n'
        )
        hits = _scan(tmp_path)
        assert hits == []

    def test_gate_ignores_canonical_imports(self, tmp_path):
        """``gigaevo_client`` imports must never trigger — that's the
        migration target."""
        py = tmp_path / "fake.py"
        py.write_text(
            "from gigaevo_client import GigaEvoClient\n"
            "import gigaevo_client.config\n"
        )
        hits = _scan(tmp_path)
        assert hits == []

    def test_gate_ignores_similar_named_packages(self, tmp_path):
        """``gigaevo_memory_helper`` (hypothetical sibling package)
        must not be confused with the legacy name."""
        py = tmp_path / "fake.py"
        py.write_text("from gigaevo_memory_helper import X\n")
        hits = _scan(tmp_path)
        assert hits == []
