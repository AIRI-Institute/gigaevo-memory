"""Exception hierarchy for the gigaevo-memory client."""


class MemoryError(Exception):
    """Base exception for gigaevo-memory client."""


class NotFoundError(MemoryError):
    """Entity or version not found (HTTP 404)."""


class ConflictError(MemoryError):
    """Optimistic concurrency conflict (HTTP 409/412)."""


class ConnectionError(MemoryError):
    """Cannot connect to the Memory API server."""


class ValidationError(MemoryError):
    """Request validation failed (HTTP 422)."""
