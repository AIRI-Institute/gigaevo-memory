"""Tests for the PyPI distribution split (TODO §2.1 P1).

The single ``gigaevo-memory`` distribution was split into:

  * ``gigaevo-client`` — canonical Python SDK, ships ``gigaevo_client/``
    from ``client/python/``.
  * ``gigaevo-memory`` — legacy compatibility meta-package, ships only
    the ``gigaevo_memory`` shim from ``client/python-meta/`` and
    declares ``gigaevo-client`` as a hard dependency.

These tests verify the **distribution metadata** (parsed from each
``pyproject.toml``) and the **filesystem layout**, plus that the
package each user-facing module belongs to matches what we publish.
The behavioural rename tests live in ``test_package_rename.py``;
this module only owns the packaging-shape invariants.
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent

CLIENT_PYPROJECT = REPO_ROOT / "client" / "python" / "pyproject.toml"
META_PYPROJECT = REPO_ROOT / "client" / "python-meta" / "pyproject.toml"


def _read(path: pathlib.Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Canonical distribution: gigaevo-client
# ---------------------------------------------------------------------------


class TestCanonicalDistribution:
    def test_pyproject_exists(self):
        assert CLIENT_PYPROJECT.is_file()

    def test_distribution_name_is_gigaevo_client(self):
        cfg = _read(CLIENT_PYPROJECT)
        assert cfg["project"]["name"] == "gigaevo-client"

    def test_wheel_ships_only_gigaevo_client_package(self):
        """The canonical distribution must NOT ship the legacy shim
        directory — that's the meta-package's job."""
        cfg = _read(CLIENT_PYPROJECT)
        packages = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        assert packages == ["src/gigaevo_client"]
        assert not any("gigaevo_memory" in p for p in packages)

    def test_version_pulled_from_canonical_module(self):
        cfg = _read(CLIENT_PYPROJECT)
        assert (
            cfg["tool"]["hatch"]["version"]["path"]
            == "src/gigaevo_client/__init__.py"
        )

    def test_runtime_dependencies_unchanged(self):
        """The PyPI rename must not silently change behaviour. The
        runtime dep list should still carry the same essentials."""
        cfg = _read(CLIENT_PYPROJECT)
        deps = cfg["project"]["dependencies"]
        joined = " ".join(deps)
        for must_have in ("httpx", "pydantic", "httpx-sse", "mmar-carl"):
            assert must_have in joined, must_have


# ---------------------------------------------------------------------------
# Meta-package: gigaevo-memory
# ---------------------------------------------------------------------------


class TestMetaDistribution:
    def test_pyproject_exists(self):
        assert META_PYPROJECT.is_file()

    def test_distribution_name_is_gigaevo_memory(self):
        cfg = _read(META_PYPROJECT)
        assert cfg["project"]["name"] == "gigaevo-memory"

    def test_depends_on_gigaevo_client(self):
        cfg = _read(META_PYPROJECT)
        deps = cfg["project"]["dependencies"]
        assert any(
            d == "gigaevo-client" or d.startswith("gigaevo-client") for d in deps
        ), deps

    def test_wheel_ships_only_legacy_shim(self):
        cfg = _read(META_PYPROJECT)
        packages = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        assert packages == ["src/gigaevo_memory"]
        assert not any("gigaevo_client" in p for p in packages)

    def test_shim_directory_relocated(self):
        """The shim must physically live in the meta-package's tree,
        not in the canonical package any longer."""
        new_loc = META_PYPROJECT.parent / "src" / "gigaevo_memory" / "__init__.py"
        old_loc = CLIENT_PYPROJECT.parent / "src" / "gigaevo_memory"
        assert new_loc.is_file()
        assert not old_loc.exists(), (
            "Stale shim still present in client/python/src/ — was the move incomplete?"
        )

    def test_classifier_marks_meta_as_inactive(self):
        """Surface to PyPI users that this is a compatibility shell,
        not an actively-developed package."""
        cfg = _read(META_PYPROJECT)
        classifiers = cfg["project"]["classifiers"]
        assert any("Inactive" in c for c in classifiers)


# ---------------------------------------------------------------------------
# Workspace wiring: root pyproject.toml lists both members
# ---------------------------------------------------------------------------


class TestWorkspaceConfiguration:
    ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"

    def test_both_workspaces_listed(self):
        cfg = _read(self.ROOT_PYPROJECT)
        members = cfg["tool"]["uv"]["workspace"]["members"]
        assert "client/python" in members
        assert "client/python-meta" in members

    def test_uv_sources_map_both_distributions(self):
        cfg = _read(self.ROOT_PYPROJECT)
        sources = cfg["tool"]["uv"]["sources"]
        assert sources["gigaevo-client"] == {"workspace": True}
        assert sources["gigaevo-memory"] == {"workspace": True}

    def test_root_depends_on_both_distributions(self):
        cfg = _read(self.ROOT_PYPROJECT)
        deps = set(cfg["project"]["dependencies"])
        assert "gigaevo-client" in deps
        assert "gigaevo-memory" in deps


# ---------------------------------------------------------------------------
# Runtime: each user-facing module belongs to the distribution it should
# ---------------------------------------------------------------------------


class TestRuntimePackageProvenance:
    """After ``uv sync``, ``importlib.metadata`` must report:

      * ``gigaevo_client`` shipped by the ``gigaevo-client`` distribution.
      * ``gigaevo_memory`` shipped by the ``gigaevo-memory`` distribution.

    If installation accidentally bundled the shim into ``gigaevo-client``
    again, this test would catch it.
    """

    def test_gigaevo_client_distribution_installed_at_canonical_path(self):
        """``gigaevo_client.__file__`` must resolve under
        ``client/python/src/`` — i.e. served by the canonical
        distribution, not by some accidentally-shipped second copy."""
        import importlib
        from importlib.metadata import version

        # Distribution metadata reports the right name + version.
        assert version("gigaevo-client") == "0.3.0"

        mod = importlib.import_module("gigaevo_client")
        assert mod.__file__ is not None
        path = pathlib.Path(mod.__file__).resolve()
        assert "client/python/src/gigaevo_client" in str(path), path
        assert "client/python-meta" not in str(path), path

    def test_gigaevo_memory_shim_served_from_meta_distribution(self):
        """``gigaevo_memory.__file__`` must resolve under
        ``client/python-meta/src/`` — the shim now lives in the meta
        distribution, not in the canonical one."""
        import importlib
        from importlib.metadata import version

        assert version("gigaevo-memory") >= "0.3.1"

        if "gigaevo_memory" in sys.modules:
            del sys.modules["gigaevo_memory"]
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mod = importlib.import_module("gigaevo_memory")
        assert mod.__file__ is not None
        path = pathlib.Path(mod.__file__).resolve()
        assert "client/python-meta/src/gigaevo_memory" in str(path), path
        assert "client/python/src/gigaevo_memory" not in str(path), path

    def test_meta_package_pulls_in_canonical_at_install_time(self):
        """The meta-package's ``Requires-Dist`` must mention
        ``gigaevo-client`` so ``pip install gigaevo-memory`` is enough
        to get the real code."""
        from importlib.metadata import requires

        reqs = requires("gigaevo-memory") or []
        # Look at the bare package name, ignore version specifiers.
        names = {r.split(" ")[0].split(";")[0].split("=")[0].split(">")[0].split("<")[0].strip() for r in reqs}
        assert "gigaevo-client" in names, reqs

    def test_no_pycache_in_old_location(self):
        """A leftover ``__pycache__`` in the old shim path would
        confuse Python's import machinery (it would re-resolve a
        stale ``gigaevo_memory`` from there)."""
        stale = CLIENT_PYPROJECT.parent / "src" / "gigaevo_memory"
        assert not stale.exists()


# ---------------------------------------------------------------------------
# Smoke: importing through either name still works after the split
# ---------------------------------------------------------------------------


class TestImportSmoke:
    def test_canonical_name_imports(self):
        import importlib

        mod = importlib.import_module("gigaevo_client")
        assert mod.__version__ >= "0.3.0"

    def test_legacy_name_imports_through_shim(self):
        # The shim is in a separate distribution now, so this is the
        # real test of the split — the shim must be installed
        # alongside the canonical package.
        if "gigaevo_memory" in sys.modules:
            del sys.modules["gigaevo_memory"]
        import importlib
        import warnings

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            mod = importlib.import_module("gigaevo_memory")
        assert mod.__version__ == importlib.import_module("gigaevo_client").__version__
        # The shim must still emit its rename DeprecationWarning even
        # though it's now in a separate dist.
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "gigaevo_memory" in str(w.message)
            for w in captured
        ), [str(w.message) for w in captured]
