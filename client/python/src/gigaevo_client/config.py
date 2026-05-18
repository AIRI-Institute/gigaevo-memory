"""Unified GigaEvo client configuration (P1 §2.3, iter #39).

`GigaEvoConfig` is a single immutable dataclass carrying every knob
needed to construct either :class:`MemoryClient` or
:class:`PlatformMemoryClient`. The motivation:

* Today each client has 7-8 keyword arguments with overlapping defaults
  — passing them around becomes error-prone, and changing a default in
  one place doesn't propagate.
* CARE wants to read connection details from a single place
  (`~/.config/gigaevo/config.toml` + env vars — wiring in §2.3 P2)
  and build a client without enumerating every knob.

Usage::

    from gigaevo_memory import GigaEvoConfig, MemoryClient

    cfg = GigaEvoConfig(
        memory_base_url="https://memory.gigaevo.io",
        api_key="sk-...",
        timeout=10.0,
    )
    client = MemoryClient.from_config(cfg)

Both client classes ship a :meth:`from_config` classmethod that
unpacks the config into the existing kwargs surface, so callers can
keep using the long-form ``__init__`` if they prefer.

The dataclass is **frozen** so a single config can be safely shared
across threads / clients. Use :meth:`with_overrides` to derive a
modified config without mutating the original.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from .cache import CachePolicy

if TYPE_CHECKING:
    from .embeddings import EmbeddingProvider


#: Default location operators put their TOML config in. ``GigaEvoConfig.load``
#: looks here when no explicit ``path`` is passed. Matches the XDG-ish layout
#: every other gigaevo-* tool already uses.
DEFAULT_CONFIG_PATH: Path = Path.home() / ".config" / "gigaevo" / "config.toml"


#: Map of environment variable name → ``GigaEvoConfig`` field name. Exactly
#: the three strings called out in the §2.3 P2 spec. Everything else
#: (timeouts, cache policy, etc.) goes through the TOML file — env vars
#: stay narrow so accidental shell exports can't perturb timing-sensitive
#: knobs.
_ENV_VAR_MAP: Mapping[str, str] = {
    "GIGAEVO_MEMORY_URL": "memory_base_url",
    "GIGAEVO_PLATFORM_URL": "platform_base_url",
    "GIGAEVO_API_KEY": "api_key",
}


@dataclass(frozen=True)
class GigaEvoConfig:
    """Single config object for every GigaEvo client.

    All fields have safe defaults so ``GigaEvoConfig()`` produces a
    config pointing at ``http://localhost:8000`` with TTL caching —
    the same shape as ``MemoryClient()``.
    """

    memory_base_url: str = "http://localhost:8000"
    """Base URL of the Memory API. Used as ``base_url`` by the client."""

    platform_base_url: str | None = None
    """Reserved for the §2 unified-client work. Today Memory serves
    Platform endpoints directly, so this is unused; future
    deployments may split them."""

    api_key: str | None = None
    """Plaintext API key. When set, every request carries
    ``X-API-Key: <api_key>`` — exercised by the iter #25/#28 dual-mode
    auth. ``None`` means no header (anonymous in opt-in deployments,
    401 in strict deployments)."""

    embedding_provider: EmbeddingProvider | None = None
    """Provider used for client-side embedding of search queries.
    When ``None`` the client lazily resolves a default provider."""

    cache_policy: CachePolicy = CachePolicy.TTL
    """Caching strategy: TTL, FRESHNESS_CHECK, or SSE_PUSH."""

    cache_ttl: int = 300
    """Default cache TTL in seconds (only used by the TTL policy)."""

    timeout: float = 30.0
    """HTTP request timeout in seconds. Applied to every outgoing
    request — increase for slow networks; decrease to fail-fast in
    tests."""

    freshness_on_miss: bool = False
    """When ``True``, the client revalidates cache entries on miss
    via a HEAD/ETag round-trip before treating them as authoritative."""

    sse_prefetch: bool = False
    """When ``True``, the client prefetches entities via the SSE
    firehose (`/v1/events`) to warm the cache for hot-reloaded
    chains. Costs an extra background connection."""

    def with_overrides(self, **overrides) -> "GigaEvoConfig":
        """Return a new config with ``overrides`` applied.

        Validates that every key matches a real field so a typo
        like ``with_overrides(timout=5)`` fails fast instead of
        silently being ignored.
        """
        known = {f.name for f in fields(self)}
        unknown = set(overrides) - known
        if unknown:
            raise TypeError(
                f"unknown GigaEvoConfig field(s): {sorted(unknown)}. "
                f"Valid fields: {sorted(known)}"
            )
        return replace(self, **overrides)

    def memory_client_kwargs(self) -> dict:
        """Return the kwargs subset that :class:`MemoryClient` and
        :class:`PlatformMemoryClient` accept.

        Today both classes share the same surface; this method exists
        so the unpack stays in one place when the §2 unified-client
        work adds platform-specific knobs."""
        return {
            "base_url": self.memory_base_url,
            "api_key": self.api_key,
            "embedding_provider": self.embedding_provider,
            "cache_policy": self.cache_policy,
            "cache_ttl": self.cache_ttl,
            "timeout": self.timeout,
            "freshness_on_miss": self.freshness_on_miss,
            "sse_prefetch": self.sse_prefetch,
        }

    # -----------------------------------------------------------------
    # Loaders (§2.3 P2)
    # -----------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "GigaEvoConfig":
        """Build a config from a TOML file at ``path``.

        The TOML keys must match :class:`GigaEvoConfig` field names;
        ``cache_policy`` accepts either the enum value (``"ttl"``) or
        the enum name (``"TTL"``). Unknown keys raise ``TypeError``
        with a helpful message so typos surface immediately instead
        of silently being ignored.

        Example::

            # ~/.config/gigaevo/config.toml
            memory_base_url = "https://memory.gigaevo.io"
            api_key = "sk-prod-abc123"
            timeout = 10.0
            cache_ttl = 600

        Raises:
            FileNotFoundError: when ``path`` does not exist.
            tomllib.TOMLDecodeError: on malformed TOML.
            TypeError: on unknown keys.
        """
        path = Path(path)
        with path.open("rb") as f:
            raw = tomllib.load(f)
        return cls._from_mapping(raw, source=str(path))

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        base: "GigaEvoConfig | None" = None,
    ) -> "GigaEvoConfig":
        """Build a config from environment variables.

        Recognises exactly three variables per the §2.3 P2 spec:

          * ``GIGAEVO_MEMORY_URL``    → ``memory_base_url``
          * ``GIGAEVO_PLATFORM_URL``  → ``platform_base_url``
          * ``GIGAEVO_API_KEY``       → ``api_key``

        Other fields keep their values from ``base`` (or from class
        defaults if ``base`` is None). Empty-string values are treated
        as unset so an inherited blank ``GIGAEVO_API_KEY=`` doesn't
        wipe an otherwise-valid base config.

        Args:
            env: Mapping to read from. Defaults to ``os.environ`` so
                callers can pass a custom dict for tests without
                monkeypatching the process environment.
            base: Config to overlay env vars onto. Defaults to a
                fresh ``GigaEvoConfig()``.
        """
        env = env if env is not None else os.environ
        out = base if base is not None else cls()
        overrides: dict[str, str] = {}
        for env_name, field_name in _ENV_VAR_MAP.items():
            value = env.get(env_name)
            if value:  # treat "" / None the same — operator hasn't set it
                overrides[field_name] = value
        return out.with_overrides(**overrides) if overrides else out

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> "GigaEvoConfig":
        """Compose a config from defaults < TOML file < env vars.

        Precedence (lowest to highest):

          1. Class defaults.
          2. TOML file at ``path`` (or ``~/.config/gigaevo/config.toml``
             when ``path`` is None). Skipped silently when the file
             doesn't exist — operators with no config get the same
             result as ``GigaEvoConfig()``.
          3. Environment variables (``GIGAEVO_MEMORY_URL``,
             ``GIGAEVO_PLATFORM_URL``, ``GIGAEVO_API_KEY``).

        The composite is the canonical entry point for CARE:
        ``MemoryClient.from_config(GigaEvoConfig.load())`` Just Works
        on a freshly-provisioned machine.

        Args:
            path: Override the default TOML location. Pass an explicit
                path to read a non-default file; pass ``None`` to use
                ``~/.config/gigaevo/config.toml`` when present.
            env: Override ``os.environ`` (useful in tests).
        """
        chosen_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if chosen_path.exists():
            cfg = cls.from_file(chosen_path)
        else:
            cfg = cls()
        return cls.from_env(env=env, base=cfg)

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    @classmethod
    def _from_mapping(cls, raw: Mapping, *, source: str) -> "GigaEvoConfig":
        """Build a config from a parsed TOML mapping. Validates keys."""
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise TypeError(
                f"unknown GigaEvoConfig field(s) in {source}: "
                f"{sorted(unknown)}. Valid fields: {sorted(known)}"
            )

        kwargs: dict = dict(raw)
        # Convert string cache_policy → enum (TOML doesn't carry enums).
        if "cache_policy" in kwargs and isinstance(kwargs["cache_policy"], str):
            kwargs["cache_policy"] = _coerce_cache_policy(
                kwargs["cache_policy"], source=source
            )
        return cls(**kwargs)


def _coerce_cache_policy(value: str, *, source: str) -> CachePolicy:
    """Map a TOML string to a :class:`CachePolicy`. Accepts both
    enum values (``"ttl"``) and enum names (``"TTL"``)."""
    try:
        return CachePolicy(value)
    except ValueError:
        pass
    try:
        return CachePolicy[value.upper()]
    except KeyError:
        valid = sorted(p.value for p in CachePolicy)
        raise TypeError(
            f"unknown cache_policy {value!r} in {source}. "
            f"Valid values: {valid}"
        ) from None
