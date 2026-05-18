"""Tests for the GigaEvoConfig file + env loaders (P2 §2.3, iter #40).

Covers:
  * `from_file(path)` — reads TOML, coerces enum strings, raises
    helpful errors on unknown keys or bad TOML.
  * `from_env(env)` — recognises the three documented env vars,
    ignores empty strings, overlays onto a base config when given.
  * `load(path, env)` — composite loader with documented precedence
    (env > file > defaults).
  * `DEFAULT_CONFIG_PATH` resolves to `~/.config/gigaevo/config.toml`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gigaevo_memory import CachePolicy, GigaEvoConfig
from gigaevo_memory.config import DEFAULT_CONFIG_PATH


# ---------------------------------------------------------------------------
# DEFAULT_CONFIG_PATH
# ---------------------------------------------------------------------------


class TestDefaultPath:
    def test_resolves_to_user_config_directory(self):
        assert DEFAULT_CONFIG_PATH == Path.home() / ".config" / "gigaevo" / "config.toml"


# ---------------------------------------------------------------------------
# from_file
# ---------------------------------------------------------------------------


class TestFromFile:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "config.toml"
        p.write_text(content)
        return p

    def test_minimal_toml_loads_with_defaults_filled(self, tmp_path):
        path = self._write(tmp_path, "")
        cfg = GigaEvoConfig.from_file(path)
        assert cfg.memory_base_url == "http://localhost:8000"
        assert cfg.api_key is None

    def test_explicit_values_override_defaults(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            memory_base_url = "https://memory.gigaevo.io"
            api_key = "sk-prod-abc123"
            timeout = 10.0
            cache_ttl = 600
            """,
        )
        cfg = GigaEvoConfig.from_file(path)
        assert cfg.memory_base_url == "https://memory.gigaevo.io"
        assert cfg.api_key == "sk-prod-abc123"
        assert cfg.timeout == 10.0
        assert cfg.cache_ttl == 600

    def test_cache_policy_value_string(self, tmp_path):
        """TOML can't carry an enum so we accept the value string."""
        path = self._write(tmp_path, 'cache_policy = "ttl"')
        cfg = GigaEvoConfig.from_file(path)
        assert cfg.cache_policy == CachePolicy.TTL

    def test_cache_policy_enum_name(self, tmp_path):
        """Operators may write the upper-case enum name; accept both."""
        path = self._write(tmp_path, 'cache_policy = "TTL"')
        cfg = GigaEvoConfig.from_file(path)
        assert cfg.cache_policy == CachePolicy.TTL

    def test_unknown_key_raises_with_helpful_message(self, tmp_path):
        path = self._write(tmp_path, 'memry_url = "x"')  # typo
        with pytest.raises(TypeError, match="unknown GigaEvoConfig field"):
            GigaEvoConfig.from_file(path)

    def test_unknown_key_lists_valid_field_names(self, tmp_path):
        path = self._write(tmp_path, 'foo = "bar"')
        with pytest.raises(TypeError) as exc:
            GigaEvoConfig.from_file(path)
        msg = str(exc.value)
        assert "['foo']" in msg
        assert "memory_base_url" in msg  # valid field listed in error

    def test_unknown_cache_policy_raises(self, tmp_path):
        path = self._write(tmp_path, 'cache_policy = "magic"')
        with pytest.raises(TypeError, match="unknown cache_policy"):
            GigaEvoConfig.from_file(path)

    def test_missing_file_raises_filenotfound(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GigaEvoConfig.from_file(tmp_path / "nope.toml")

    def test_accepts_string_path(self, tmp_path):
        path = self._write(tmp_path, 'api_key = "sk-from-string-path"')
        cfg = GigaEvoConfig.from_file(str(path))
        assert cfg.api_key == "sk-from-string-path"


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


class TestFromEnv:
    def test_three_documented_vars_recognised(self):
        env = {
            "GIGAEVO_MEMORY_URL": "https://m.gigaevo.io",
            "GIGAEVO_PLATFORM_URL": "https://p.gigaevo.io",
            "GIGAEVO_API_KEY": "sk-env",
            "PATH": "/usr/bin",  # noise — must be ignored
        }
        cfg = GigaEvoConfig.from_env(env=env)
        assert cfg.memory_base_url == "https://m.gigaevo.io"
        assert cfg.platform_base_url == "https://p.gigaevo.io"
        assert cfg.api_key == "sk-env"

    def test_no_env_vars_returns_defaults(self):
        cfg = GigaEvoConfig.from_env(env={})
        assert cfg == GigaEvoConfig()

    def test_empty_string_treated_as_unset(self):
        """An inherited blank value mustn't wipe a real base setting."""
        base = GigaEvoConfig(api_key="sk-base")
        env = {"GIGAEVO_API_KEY": ""}
        cfg = GigaEvoConfig.from_env(env=env, base=base)
        assert cfg.api_key == "sk-base"

    def test_overlays_onto_base(self):
        base = GigaEvoConfig(
            memory_base_url="http://from-file.test",
            api_key="from-file",
            timeout=99.0,
        )
        env = {"GIGAEVO_API_KEY": "from-env"}
        cfg = GigaEvoConfig.from_env(env=env, base=base)
        # Env wins for api_key, base preserved elsewhere.
        assert cfg.api_key == "from-env"
        assert cfg.memory_base_url == "http://from-file.test"
        assert cfg.timeout == 99.0

    def test_partial_env_keeps_base_for_other_fields(self):
        base = GigaEvoConfig(
            memory_base_url="http://base.test",
            platform_base_url="http://base-platform.test",
        )
        env = {"GIGAEVO_MEMORY_URL": "http://env.test"}  # only one set
        cfg = GigaEvoConfig.from_env(env=env, base=base)
        assert cfg.memory_base_url == "http://env.test"
        assert cfg.platform_base_url == "http://base-platform.test"

    def test_defaults_to_os_environ_when_no_arg(self, monkeypatch):
        monkeypatch.setenv("GIGAEVO_API_KEY", "from-process-env")
        cfg = GigaEvoConfig.from_env()
        assert cfg.api_key == "from-process-env"


# ---------------------------------------------------------------------------
# load — composite
# ---------------------------------------------------------------------------


class TestLoad:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "config.toml"
        p.write_text(content)
        return p

    def test_missing_file_yields_defaults_plus_env(self, tmp_path):
        env = {"GIGAEVO_API_KEY": "sk-only-env"}
        cfg = GigaEvoConfig.load(tmp_path / "nope.toml", env=env)
        assert cfg.api_key == "sk-only-env"
        assert cfg.memory_base_url == "http://localhost:8000"  # default

    def test_file_only_when_env_empty(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            memory_base_url = "http://file.test"
            api_key = "from-file"
            """,
        )
        cfg = GigaEvoConfig.load(path, env={})
        assert cfg.memory_base_url == "http://file.test"
        assert cfg.api_key == "from-file"

    def test_env_overrides_file(self, tmp_path):
        """Documented precedence: env > file > defaults."""
        path = self._write(
            tmp_path,
            """
            memory_base_url = "http://file.test"
            api_key = "from-file"
            timeout = 5.5
            """,
        )
        env = {
            "GIGAEVO_MEMORY_URL": "http://env.test",
            "GIGAEVO_API_KEY": "from-env",
        }
        cfg = GigaEvoConfig.load(path, env=env)
        # env wins for the two it sets...
        assert cfg.memory_base_url == "http://env.test"
        assert cfg.api_key == "from-env"
        # ...but file-only fields survive
        assert cfg.timeout == 5.5

    def test_no_file_no_env_returns_defaults(self, tmp_path):
        cfg = GigaEvoConfig.load(tmp_path / "nope.toml", env={})
        assert cfg == GigaEvoConfig()

    def test_default_path_used_when_no_arg(self, monkeypatch, tmp_path):
        """When ``path`` is None, ``load`` falls back to
        ``~/.config/gigaevo/config.toml`` — proven by pointing HOME at
        a tmpdir and writing the canonical layout."""
        monkeypatch.setenv("HOME", str(tmp_path))
        # Recompute via patching the module-level DEFAULT_CONFIG_PATH
        # since the constant was bound at import time using
        # ``Path.home()``.
        cfg_dir = tmp_path / ".config" / "gigaevo"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.toml").write_text('api_key = "from-default-path"')

        from gigaevo_memory import config as _config

        monkeypatch.setattr(
            _config,
            "DEFAULT_CONFIG_PATH",
            cfg_dir / "config.toml",
        )

        cfg = GigaEvoConfig.load(env={})
        assert cfg.api_key == "from-default-path"

    def test_load_safe_against_polluted_process_env(self, tmp_path, monkeypatch):
        """Tests must not depend on the caller's shell environment.
        Passing ``env={}`` explicitly proves the loader is overrideable."""
        monkeypatch.setenv("GIGAEVO_API_KEY", "leak-from-shell")
        cfg = GigaEvoConfig.load(tmp_path / "nope.toml", env={})
        assert cfg.api_key is None  # explicit empty env shielded us


# ---------------------------------------------------------------------------
# Integration with MemoryClient.from_config
# ---------------------------------------------------------------------------


class TestIntegrationWithClient:
    def test_config_load_then_client_from_config(self, tmp_path):
        """The canonical CARE entry point:
        ``MemoryClient.from_config(GigaEvoConfig.load())`` Just Works."""
        path = tmp_path / "c.toml"
        path.write_text(
            """
            memory_base_url = "https://e2e.test"
            api_key = "sk-e2e"
            """
        )
        cfg = GigaEvoConfig.load(path, env={})

        from gigaevo_memory import MemoryClient
        client = MemoryClient.from_config(cfg)
        assert client._base_url == "https://e2e.test"
        assert client._http.headers.get("X-API-Key") == "sk-e2e"

    def test_env_overrides_file_e2e(self, tmp_path):
        path = tmp_path / "c.toml"
        path.write_text('api_key = "from-file"')
        env = {"GIGAEVO_API_KEY": "from-env-wins"}
        cfg = GigaEvoConfig.load(path, env=env)

        from gigaevo_memory import MemoryClient
        client = MemoryClient.from_config(cfg)
        assert client._http.headers.get("X-API-Key") == "from-env-wins"


# ---------------------------------------------------------------------------
# Defensive: process-environment hygiene fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _scrub_gigaevo_env(monkeypatch):
    """Ensure GIGAEVO_* env vars set by the developer's shell don't
    bleed into tests that use ``env=`` overrides."""
    for key in list(os.environ):
        if key.startswith("GIGAEVO_"):
            monkeypatch.delenv(key, raising=False)
    yield
