"""Unit tests for ``_validate_carl_dag`` (no DB required).

The validator gatekeeps POST/PUT /v1/chains. The key regression guarded
here: real mmar-carl chains serialise their version field as
``format_version`` (an int), not ``version`` — the validator must accept
that spelling or every Production chain save 400s.
"""

import pytest
from fastapi import HTTPException

from app.routers.chains import _validate_carl_dag


def _content(**overrides):
    base = {
        "format_version": 1,
        "max_workers": 3,
        "metadata": {"name": "weather"},
        "search_config": {"strategy": "substring"},
        "steps": [
            {"number": 1, "dependencies": []},
            {"number": 2, "dependencies": [1]},
        ],
    }
    base.update(overrides)
    return base


class TestVersionField:
    def test_format_version_accepted(self):
        # Canonical mmar-carl serialisation — must not raise.
        _validate_carl_dag(_content())

    def test_legacy_version_accepted(self):
        content = _content()
        del content["format_version"]
        content["version"] = "1.1"
        _validate_carl_dag(content)

    def test_missing_both_version_keys_raises(self):
        content = _content()
        del content["format_version"]
        with pytest.raises(HTTPException) as exc:
            _validate_carl_dag(content)
        assert exc.value.status_code == 400
        assert "version" in exc.value.detail


class TestStructuralValidation:
    @pytest.mark.parametrize("field", ["max_workers", "metadata", "search_config", "steps"])
    def test_missing_required_field_raises(self, field):
        content = _content()
        del content[field]
        with pytest.raises(HTTPException) as exc:
            _validate_carl_dag(content)
        assert exc.value.status_code == 400
        assert field in exc.value.detail

    def test_empty_steps_raises(self):
        with pytest.raises(HTTPException) as exc:
            _validate_carl_dag(_content(steps=[]))
        assert exc.value.status_code == 400

    def test_cycle_raises(self):
        content = _content(
            steps=[
                {"number": 1, "dependencies": [2]},
                {"number": 2, "dependencies": [1]},
            ]
        )
        with pytest.raises(HTTPException) as exc:
            _validate_carl_dag(content)
        assert exc.value.status_code == 400
