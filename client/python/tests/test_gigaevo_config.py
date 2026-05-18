"""Tests for the unified GigaEvoConfig (P1 §2.3, iter #39).

Covers:
  * Dataclass defaults match the standalone client defaults.
  * Frozen — no field mutation.
  * `with_overrides` returns a new instance, validates field names.
  * `memory_client_kwargs` exposes exactly the keys both clients accept.
  * `MemoryClient.from_config` / `PlatformMemoryClient.from_config`
    build an instance with the right surface.
  * `api_key` propagates into the `X-API-Key` HTTP header on every
    request the client makes.
"""

from __future__ import annotations

import dataclasses

import pytest

from gigaevo_memory import (
    CachePolicy,
    GigaEvoConfig,
    MemoryClient,
    PlatformMemoryClient,
)


# ---------------------------------------------------------------------------
# Dataclass shape + defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_values(self):
        cfg = GigaEvoConfig()
        assert cfg.memory_base_url == "http://localhost:8000"
        assert cfg.platform_base_url is None
        assert cfg.api_key is None
        assert cfg.embedding_provider is None
        assert cfg.cache_policy == CachePolicy.TTL
        assert cfg.cache_ttl == 300
        assert cfg.timeout == 30.0
        assert cfg.freshness_on_miss is False
        assert cfg.sse_prefetch is False

    def test_config_is_frozen(self):
        cfg = GigaEvoConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.api_key = "leaked"  # type: ignore[misc]

    def test_explicit_construction(self):
        cfg = GigaEvoConfig(
            memory_base_url="https://memory.test/",
            api_key="sk-test",
            timeout=10.0,
        )
        assert cfg.memory_base_url == "https://memory.test/"
        assert cfg.api_key == "sk-test"
        assert cfg.timeout == 10.0
        # Untouched fields keep defaults.
        assert cfg.cache_ttl == 300


# ---------------------------------------------------------------------------
# with_overrides
# ---------------------------------------------------------------------------


class TestWithOverrides:
    def test_returns_new_instance(self):
        cfg = GigaEvoConfig()
        new = cfg.with_overrides(api_key="sk-1")
        assert new is not cfg
        assert new.api_key == "sk-1"
        assert cfg.api_key is None  # original untouched

    def test_partial_override(self):
        cfg = GigaEvoConfig(timeout=5.0, api_key="a")
        new = cfg.with_overrides(api_key="b")
        assert new.timeout == 5.0  # unchanged
        assert new.api_key == "b"

    def test_unknown_field_raises_with_helpful_message(self):
        cfg = GigaEvoConfig()
        with pytest.raises(TypeError, match="unknown GigaEvoConfig field"):
            cfg.with_overrides(timout=5)  # typo

    def test_multiple_unknown_fields_listed_alphabetically(self):
        cfg = GigaEvoConfig()
        with pytest.raises(TypeError) as exc:
            cfg.with_overrides(foo=1, bar=2)
        assert "['bar', 'foo']" in str(exc.value)


# ---------------------------------------------------------------------------
# memory_client_kwargs
# ---------------------------------------------------------------------------


class TestMemoryClientKwargs:
    def test_kwargs_match_client_init_surface(self):
        """The kwargs subset must be acceptable by both client classes."""
        cfg = GigaEvoConfig()
        kwargs = cfg.memory_client_kwargs()
        # Should accept and apply without error.
        MemoryClient(**kwargs).close() if hasattr(
            MemoryClient(**kwargs), "close"
        ) else None
        PlatformMemoryClient(**kwargs)

    def test_kwargs_uses_memory_base_url(self):
        cfg = GigaEvoConfig(memory_base_url="https://other.test/")
        kwargs = cfg.memory_client_kwargs()
        assert kwargs["base_url"] == "https://other.test/"

    def test_kwargs_carries_api_key(self):
        cfg = GigaEvoConfig(api_key="sk-abc")
        assert cfg.memory_client_kwargs()["api_key"] == "sk-abc"


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


class TestFromConfig:
    def test_memory_client_from_default_config(self):
        cfg = GigaEvoConfig()
        c = MemoryClient.from_config(cfg)
        assert c._base_url == "http://localhost:8000"
        assert c._api_key is None

    def test_memory_client_from_explicit_config(self):
        cfg = GigaEvoConfig(
            memory_base_url="https://memory.test/",
            api_key="sk-test",
            timeout=7.5,
        )
        c = MemoryClient.from_config(cfg)
        assert c._base_url == "https://memory.test"  # rstrip("/")
        assert c._api_key == "sk-test"

    def test_platform_client_from_config(self):
        cfg = GigaEvoConfig(api_key="sk-platform")
        c = PlatformMemoryClient.from_config(cfg)
        assert c._api_key == "sk-platform"

    def test_trailing_slash_stripped(self):
        """``base_url`` is normalised by the client; config field itself
        retains the trailing slash exactly as given (the dataclass is
        the SoT for what the operator typed)."""
        cfg = GigaEvoConfig(memory_base_url="http://x/")
        assert cfg.memory_base_url == "http://x/"
        c = MemoryClient.from_config(cfg)
        assert c._base_url == "http://x"


# ---------------------------------------------------------------------------
# X-API-Key header propagation
# ---------------------------------------------------------------------------


class TestApiKeyHeader:
    def test_api_key_sets_header_on_underlying_http_client(self):
        cfg = GigaEvoConfig(api_key="sk-header-test")
        c = MemoryClient.from_config(cfg)
        assert c._http.headers.get("X-API-Key") == "sk-header-test"

    def test_no_api_key_no_header(self):
        c = MemoryClient.from_config(GigaEvoConfig())
        assert "X-API-Key" not in c._http.headers

    def test_explicit_init_arg_also_sets_header(self):
        """Plumbing works whether the operator uses `from_config` or
        the long-form constructor."""
        c = MemoryClient(api_key="direct-construction")
        assert c._http.headers.get("X-API-Key") == "direct-construction"

    def test_empty_string_api_key_does_not_set_header(self):
        """Empty string is treated as missing — matches server-side
        opt-in semantics (`X-API-Key: ''` would still hit the dual-mode
        invalid-key path)."""
        c = MemoryClient(api_key="")
        assert "X-API-Key" not in c._http.headers


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_existing_long_form_still_works(self):
        """No keyword args means the old default behaviour is preserved."""
        c = MemoryClient()
        assert c._base_url == "http://localhost:8000"
        assert c._api_key is None
        assert "X-API-Key" not in c._http.headers

    def test_kwargs_other_than_api_key_still_work(self):
        """Existing callers passing every original kwarg keep working."""
        c = MemoryClient(
            base_url="http://x",
            cache_policy=CachePolicy.TTL,
            cache_ttl=60,
            timeout=5.0,
            freshness_on_miss=True,
            sse_prefetch=False,
        )
        assert c._base_url == "http://x"
        assert c._api_key is None
