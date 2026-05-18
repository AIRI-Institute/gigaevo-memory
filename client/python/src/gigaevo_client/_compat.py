"""CARL integration adapters and JSON-serialization helpers.

Provides typed conversion between raw dicts and CARL objects.

Note: mmar_carl is a required dependency for this package.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from mmar_carl import AnyStepDescription, ContextQuery, ReasoningChain, StepDescription


def to_jsonable(value: Any) -> Any:
    """Recursively convert model-like objects to plain JSON-compatible data."""
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return to_jsonable(model_dump(mode="json"))
        except TypeError:
            return to_jsonable(model_dump())

    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        return to_jsonable(dict_method())

    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]

    return value


def _normalize_step_context_queries(
    queries: Iterable[ContextQuery | str] | None,
) -> list[dict[str, Any] | str]:
    """Normalize ContextQuery objects to JSON-serializable dicts."""
    if not queries:
        return []
    normalized: list[dict[str, Any] | str] = []
    for query in queries:
        if isinstance(query, ContextQuery):
            normalized.append(to_jsonable(query))
        else:
            normalized.append(to_jsonable(query))
    return normalized


def _patch_step_dict(step_obj: AnyStepDescription, step_dict: dict[str, Any]) -> dict[str, Any]:
    """Patch CARL step dict with fields omitted by ReasoningChain.to_dict()."""
    if "step_context_queries" in step_dict:
        step_dict["step_context_queries"] = _normalize_step_context_queries(
            step_dict.get("step_context_queries")
        )

    if hasattr(step_obj, "llm_config"):
        llm_config = getattr(step_obj, "llm_config")
        if llm_config is not None:
            step_dict["llm_config"] = to_jsonable(llm_config)
        elif "llm_config" not in step_dict:
            step_dict["llm_config"] = None

    return step_dict


def chain_from_content(content_json: dict[str, Any]) -> ReasoningChain:
    """Deserialize content_json to a ReasoningChain with typed steps."""
    payload = copy.deepcopy(content_json)
    legacy_chain = ReasoningChain.from_dict(payload, use_typed_steps=False)
    typed_steps = [step.to_typed_step() for step in legacy_chain.steps]
    return ReasoningChain(
        steps=typed_steps,
        max_workers=legacy_chain.max_workers,
        enable_progress=legacy_chain.enable_progress,
        metadata=legacy_chain.metadata,
        search_config=legacy_chain.prompt_template.search_config,
    )


def chain_to_content(chain: ReasoningChain) -> dict[str, Any]:
    """Serialize a ReasoningChain to a dict."""
    data = chain.to_dict()
    data_steps = data.get("steps", [])
    for step_obj, step_dict in zip(chain.steps, data_steps):
        _patch_step_dict(step_obj, step_dict)
    return data


def step_from_content(content_json: dict[str, Any]) -> AnyStepDescription:
    """Deserialize content_json to a typed CARL step."""
    return StepDescription.model_validate(content_json).to_typed_step()


def step_to_content(step: AnyStepDescription) -> dict[str, Any]:
    """Serialize a typed CARL step to a dict."""
    step_dict = to_jsonable(step)
    step_dict["step_type"] = str(step.step_type)
    if "config" in step_dict:
        step_dict["step_config"] = step_dict.pop("config")
    return _patch_step_dict(step, step_dict)
