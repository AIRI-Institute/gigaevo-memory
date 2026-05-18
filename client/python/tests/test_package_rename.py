"""Tests for the gigaevo_memory → gigaevo_client rename (P1 §2.1, iter #42).

Covers:
  * Both import paths resolve.
  * ``MemoryClient`` is an alias for ``GigaEvoClient`` (same object).
  * ``isinstance`` checks across the two names succeed.
  * Submodule access via the legacy name works
    (e.g. ``from gigaevo_memory.config import GigaEvoConfig``).
  * The legacy shim emits a :class:`DeprecationWarning` on import.
  * Version metadata reports the new ``0.3.0`` semver.
"""

from __future__ import annotations

import sys
import warnings

import pytest


# ---------------------------------------------------------------------------
# Canonical and legacy import paths resolve to the same objects
# ---------------------------------------------------------------------------


class TestCanonicalImportPath:
    def test_gigaevo_client_imports(self):
        import gigaevo_client
        assert hasattr(gigaevo_client, "__version__")
        assert hasattr(gigaevo_client, "GigaEvoClient")
        assert hasattr(gigaevo_client, "MemoryClient")
        assert hasattr(gigaevo_client, "GigaEvoConfig")

    def test_version_is_030(self):
        import gigaevo_client
        assert gigaevo_client.__version__ == "0.3.0"

    def test_from_gigaevo_client_works(self):
        from gigaevo_client import GigaEvoClient, MemoryClient, GigaEvoConfig
        assert GigaEvoClient is not None
        assert MemoryClient is not None
        assert GigaEvoConfig is not None


class TestLegacyImportPath:
    def test_top_level_names_work(self):
        from gigaevo_memory import GigaEvoClient, MemoryClient, GigaEvoConfig
        assert GigaEvoClient is not None
        assert MemoryClient is not None
        assert GigaEvoConfig is not None

    def test_submodule_access(self):
        """``from gigaevo_memory.config import GigaEvoConfig`` is what
        most call sites use. ``sys.modules`` aliasing in the shim
        makes this work without changes."""
        from gigaevo_memory.config import GigaEvoConfig as cfg_via_legacy
        from gigaevo_client.config import GigaEvoConfig as cfg_via_canonical
        assert cfg_via_legacy is cfg_via_canonical

    def test_models_submodule_access(self):
        from gigaevo_memory.models import EntityResponse as r1
        from gigaevo_client.models import EntityResponse as r2
        assert r1 is r2

    def test_legacy_version_mirrors_canonical(self):
        import gigaevo_memory
        import gigaevo_client
        assert gigaevo_memory.__version__ == gigaevo_client.__version__


# ---------------------------------------------------------------------------
# Class identity: MemoryClient is GigaEvoClient
# ---------------------------------------------------------------------------


class TestMemoryClientAlias:
    def test_same_object_via_canonical_package(self):
        from gigaevo_client import GigaEvoClient, MemoryClient
        assert MemoryClient is GigaEvoClient

    def test_same_object_via_legacy_package(self):
        from gigaevo_memory import GigaEvoClient, MemoryClient
        assert MemoryClient is GigaEvoClient

    def test_same_object_across_packages(self):
        from gigaevo_client import GigaEvoClient as new
        from gigaevo_memory import MemoryClient as old
        assert old is new

    def test_isinstance_works_for_both_names(self):
        from gigaevo_client import GigaEvoClient
        from gigaevo_memory import MemoryClient
        instance = GigaEvoClient()
        assert isinstance(instance, GigaEvoClient)
        assert isinstance(instance, MemoryClient)  # alias

    def test_module_qualname_points_at_new_package(self):
        """``GigaEvoClient.__module__`` reports the canonical home so
        ``repr(instance)`` shows ``gigaevo_client.client.GigaEvoClient``
        not the legacy name."""
        from gigaevo_client import GigaEvoClient
        assert GigaEvoClient.__module__ == "gigaevo_client.client"
        assert GigaEvoClient.__name__ == "GigaEvoClient"


# ---------------------------------------------------------------------------
# DeprecationWarning emission
# ---------------------------------------------------------------------------


class TestDeprecationWarning:
    def test_legacy_import_fires_warning(self):
        """Importing the shim emits a single DeprecationWarning. The
        package may already be cached in ``sys.modules`` from earlier
        tests, so we force a fresh import."""
        sys.modules.pop("gigaevo_memory", None)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            import gigaevo_memory  # noqa: F401
        msgs = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        assert any(
            "renamed" in m and "gigaevo_client" in m for m in msgs
        ), f"expected rename warning, got: {msgs}"

    def test_warning_mentions_target_version(self):
        sys.modules.pop("gigaevo_memory", None)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            import gigaevo_memory  # noqa: F401
        msgs = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        assert any("0.3.0" in m for m in msgs), f"expected version mention, got: {msgs}"

    def test_canonical_import_silent(self):
        """``import gigaevo_client`` does NOT emit a deprecation —
        only the legacy path complains."""
        sys.modules.pop("gigaevo_client", None)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            import gigaevo_client  # noqa: F401
        rename_warnings = [
            w for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "gigaevo_memory" in str(w.message).lower()
        ]
        assert rename_warnings == []


# ---------------------------------------------------------------------------
# Type-check identity for the `__all__` exports
# ---------------------------------------------------------------------------


class TestAllExports:
    def test_canonical_all_contains_both_client_names(self):
        import gigaevo_client
        assert "GigaEvoClient" in gigaevo_client.__all__
        assert "MemoryClient" in gigaevo_client.__all__

    def test_legacy_mirrors_canonical_all(self):
        import gigaevo_client
        import gigaevo_memory
        assert gigaevo_memory.__all__ == gigaevo_client.__all__


# ---------------------------------------------------------------------------
# GigaEvoConfig.from_config helper still works under the new name
# ---------------------------------------------------------------------------


class TestFromConfigRoundTrip:
    def test_new_name_with_config(self):
        from gigaevo_client import GigaEvoClient, GigaEvoConfig
        client = GigaEvoClient.from_config(GigaEvoConfig(api_key="sk-rename"))
        assert client._http.headers.get("X-API-Key") == "sk-rename"

    def test_legacy_name_with_config_still_works(self):
        """Existing callers using ``MemoryClient.from_config`` keep
        working after the rename — the alias is the same class."""
        from gigaevo_memory import MemoryClient, GigaEvoConfig
        client = MemoryClient.from_config(GigaEvoConfig(api_key="sk-legacy"))
        assert client._http.headers.get("X-API-Key") == "sk-legacy"


# ---------------------------------------------------------------------------
# Unknown attribute path
# ---------------------------------------------------------------------------


class TestUnknownAttribute:
    def test_unknown_canonical_attr_raises(self):
        import gigaevo_client
        with pytest.raises(AttributeError, match="gigaevo_client"):
            gigaevo_client.no_such_thing  # noqa: B018

    def test_unknown_legacy_attr_mentions_both_packages(self):
        """The shim's AttributeError should hint that the name isn't
        in the renamed package either, so users don't think the alias
        is hiding something."""
        import gigaevo_memory
        with pytest.raises(AttributeError, match="gigaevo_client"):
            gigaevo_memory.no_such_thing  # noqa: B018
