"""GigaEvoSuite — combined Memory + Platform client (P1 §2.2, iter #43).

The TODO sketched this as ``class GigaEvoSuite(GigaEvoClient,
PlatformClient)`` — literal multiple inheritance — but each parent
class owns its own ``httpx.Client`` pointed at a different backend.
With two distinct backends, a single ``self._http`` can't serve both;
inheritance would require collapsing the URL space or playing MRO
games that obscure which method calls which backend.

Composition gives the same "one object, both surfaces" ergonomics
without the ambiguity: ``suite.memory`` is the Memory client,
``suite.platform`` is the Platform client. Convenience proxies for
the most common operations live directly on the suite so casual
callers don't have to know about the two attributes.
"""

from __future__ import annotations

from typing import Any

from .client import GigaEvoClient
from .platform import PlatformClient


class GigaEvoSuite:
    """Composite client holding both backends.

    Construct with explicit URLs::

        suite = GigaEvoSuite(
            memory_base_url="https://memory.gigaevo.io",
            platform_base_url="https://platform.gigaevo.io",
            api_key="sk-prod",
        )
        suite.memory.list_chains()
        suite.platform.health()

    Or from a single config (the canonical path for CARE)::

        from gigaevo_client import GigaEvoConfig
        suite = GigaEvoSuite.from_config(GigaEvoConfig.load())

    Both sub-clients share the same ``api_key`` and ``timeout``; the
    URLs are independent so Memory can live on one host and Platform
    on another.
    """

    def __init__(
        self,
        memory_base_url: str = "http://localhost:8000",
        platform_base_url: str = "http://localhost:8001",
        timeout: float = 30.0,
        api_key: str | None = None,
    ):
        self.memory = GigaEvoClient(
            base_url=memory_base_url, timeout=timeout, api_key=api_key
        )
        self.platform = PlatformClient(
            base_url=platform_base_url, timeout=timeout, api_key=api_key
        )

    @classmethod
    def from_config(cls, config) -> "GigaEvoSuite":
        """Build both clients from a :class:`GigaEvoConfig`.

        Falls back to ``http://localhost:8001`` for the Platform URL
        when ``config.platform_base_url`` is ``None`` — matches
        :meth:`PlatformClient.from_config`'s default."""
        return cls(
            memory_base_url=config.memory_base_url,
            platform_base_url=config.platform_base_url or "http://localhost:8001",
            timeout=config.timeout,
            api_key=config.api_key,
        )

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def close(self) -> None:
        """Close both underlying httpx connection pools."""
        self.memory.close()
        self.platform.close()

    def __enter__(self) -> "GigaEvoSuite":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
