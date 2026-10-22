"""CORS middleware tests (CARE PREPARE §1.9).

`CORSMiddleware` is configured from `Settings.cors_allowed_origins` (a
comma-separated string env). These tests verify three things:

1. The settings parser splits / strips correctly.
2. The middleware is wired into the FastAPI app.
3. A preflight `OPTIONS` request from an allowed origin gets the
   right `access-control-allow-*` headers back.
"""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.middleware.cors import CORSMiddleware

from app import main as app_main
from app.config import Settings


class TestCorsAllowedOriginsList:
    def test_wildcard_default(self):
        s = Settings(cors_allowed_origins="*")
        assert s.cors_allowed_origins_list == ["*"]

    def test_single_origin(self):
        s = Settings(cors_allowed_origins="https://care.example")
        assert s.cors_allowed_origins_list == ["https://care.example"]

    def test_comma_separated(self):
        s = Settings(cors_allowed_origins="https://a.example,https://b.example")
        assert s.cors_allowed_origins_list == [
            "https://a.example",
            "https://b.example",
        ]

    def test_whitespace_stripped(self):
        s = Settings(cors_allowed_origins="  https://a.example , https://b.example  ")
        assert s.cors_allowed_origins_list == [
            "https://a.example",
            "https://b.example",
        ]

    def test_empty_string_yields_empty_list(self):
        s = Settings(cors_allowed_origins="")
        assert s.cors_allowed_origins_list == []

    def test_blank_tokens_are_dropped(self):
        s = Settings(cors_allowed_origins="https://a.example,,, ,https://b.example")
        assert s.cors_allowed_origins_list == [
            "https://a.example",
            "https://b.example",
        ]


class TestCorsMiddlewareWired:
    def test_corsmiddleware_in_app_stack(self):
        """``CORSMiddleware`` is registered on the FastAPI app."""
        middleware_classes = [m.cls for m in app_main.app.user_middleware]
        assert CORSMiddleware in middleware_classes


@pytest.mark.asyncio
async def test_preflight_wildcard_returns_allow_origin():
    """OPTIONS preflight from a browser gets ``access-control-allow-origin``."""
    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/healthz",
            headers={
                "Origin": "https://care.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
    # With the default wildcard, Starlette echoes the request origin back
    # (when credentials are enabled it falls back to the literal origin
    # rather than "*"). Either response is acceptable for the wildcard
    # default; the key assertion is that the header is set at all.
    assert "access-control-allow-origin" in {k.lower() for k in resp.headers}
    assert resp.status_code in (200, 204)


@pytest.mark.asyncio
async def test_explicit_origin_list_is_honored(monkeypatch):
    """When ``CORS_ALLOWED_ORIGINS`` is an explicit list, only those
    origins get an allow-origin header back."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://care.example")
    # Reload settings + main so the new env takes effect for a fresh app
    from app import config as config_mod

    importlib.reload(config_mod)
    reloaded_main = importlib.reload(app_main)
    try:
        assert config_mod.settings.cors_allowed_origins_list == [
            "https://care.example",
        ]
        transport = ASGITransport(app=reloaded_main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            allowed = await client.options(
                "/healthz",
                headers={
                    "Origin": "https://care.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            denied = await client.options(
                "/healthz",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert (
            allowed.headers.get("access-control-allow-origin")
            == "https://care.example"
        )
        assert "access-control-allow-origin" not in denied.headers
    finally:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        importlib.reload(config_mod)
        importlib.reload(app_main)
