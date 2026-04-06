"""Helpers for validating and serializing BYO vectors."""

from __future__ import annotations

import math
from collections.abc import Sequence


def validate_vector(
    vector: Sequence[float],
    *,
    expected_dimension: int,
    label: str,
) -> list[float]:
    """Validate an incoming vector against the configured contract."""
    if not vector:
        raise ValueError(f"{label} must not be empty")
    if len(vector) != expected_dimension:
        raise ValueError(
            f"{label} must have exactly {expected_dimension} dimensions"
        )

    normalized: list[float] = []
    norm_sq = 0.0
    for value in vector:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{label} must contain only finite numbers")
        normalized.append(numeric)
        norm_sq += numeric * numeric

    if norm_sq == 0.0:
        raise ValueError(f"{label} must have non-zero norm")

    return normalized


def serialize_vector(vector: Sequence[float]) -> str:
    """Serialize a vector using pgvector's text input format."""
    return "[" + ",".join(format(value, ".17g") for value in vector) + "]"
