"""Legacy import shim for ``gigaevo_memory``.

The package was renamed to ``gigaevo_client`` in 0.3.0. This module
keeps the old import path working with a one-time
:class:`DeprecationWarning` so callers see the rename signal without
their code breaking.

Migration: replace ``from gigaevo_memory import X`` with
``from gigaevo_client import X``. ``MemoryClient`` remains as an
alias for ``GigaEvoClient`` so ``isinstance`` checks keep working.

The shim re-exports every public name listed in
``gigaevo_client.__all__`` plus every submodule (``gigaevo_memory.X``
maps to ``gigaevo_client.X`` for every X). ``__getattr__`` covers
any obscure top-level name that's not in ``__all__``.
"""

from __future__ import annotations

import importlib
import sys
import warnings as _warnings

# Re-emit the deprecation notice exactly once per process — repeated
# imports from different modules during a single test run shouldn't
# spam the logs.
_warnings.warn(
    "The 'gigaevo_memory' package was renamed to 'gigaevo_client' in 0.3.0. "
    "Update your imports — 'gigaevo_memory' will be removed in a future "
    "release.",
    DeprecationWarning,
    stacklevel=2,
)

# Mirror the canonical package's __all__ so ``from gigaevo_memory
# import *`` keeps working. The imports sit below the warnings.warn
# call so the deprecation surfaces before any heavy work; ``noqa:
# E402`` silences the "import not at top of file" lint that would
# otherwise trip on the intentional ordering.
from gigaevo_client import __all__ as __all__  # noqa: F401, E402
from gigaevo_client import __version__ as __version__  # noqa: F401, E402

# Submodules of the canonical package — every ``from gigaevo_memory.X
# import Y`` needs ``sys.modules['gigaevo_memory.X']`` to resolve.
# We register them eagerly: lazy alternatives (custom MetaPathFinders)
# add complexity for negligible startup-time savings since the test
# suite imports nearly every submodule anyway.
_SUBMODULES = (
    "_base",
    "_compat",
    "agent_skills",
    "agents",
    "cache",
    "chains",
    "client",
    "config",
    "embeddings",
    "exceptions",
    "memory_cards",
    "models",
    "platform",
    "platform_client",
    "search_types",
    "suite",
    "watcher",
)
for _name in _SUBMODULES:
    sys.modules[f"gigaevo_memory.{_name}"] = importlib.import_module(
        f"gigaevo_client.{_name}"
    )
del _name


def __getattr__(name: str):
    """Forward any top-level attribute lookup to the new package."""
    import gigaevo_client as _new
    try:
        return getattr(_new, name)
    except AttributeError as exc:
        raise AttributeError(
            f"module 'gigaevo_memory' has no attribute {name!r} "
            f"(also not in renamed 'gigaevo_client')"
        ) from exc
