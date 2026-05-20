"""Tests for PlatformClient + GigaEvoSuite (P1 §2.2, iter #43).

All HTTP interactions go through ``respx`` so no real Platform server
is needed. We assert:

  * Method → URL/verb mapping matches the §2.2 spec.
  * ``X-API-Key`` header propagates from ``api_key``.
  * ``from_config`` reads ``platform_base_url`` (falling back to the
    default localhost port when None).
  * ``GigaEvoSuite`` builds two independent httpx clients pointed at
    different backends.
  * Context-manager semantics close both sub-clients.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gigaevo_client import (
    GigaEvoClient,
    GigaEvoConfig,
    GigaEvoSuite,
    PlatformClient,
)


# ---------------------------------------------------------------------------
# PlatformClient surface
# ---------------------------------------------------------------------------


class TestPlatformClientConstruction:
    def test_default_base_url(self):
        c = PlatformClient()
        assert c._base_url == "http://localhost:8001"
        assert c._api_key is None
        assert "X-API-Key" not in c._http.headers

    def test_api_key_becomes_header(self):
        c = PlatformClient(api_key="sk-plat-test")
        assert c._http.headers.get("X-API-Key") == "sk-plat-test"

    def test_trailing_slash_stripped(self):
        c = PlatformClient(base_url="https://plat.test/")
        assert c._base_url == "https://plat.test"


class TestPlatformClientFromConfig:
    def test_uses_platform_base_url(self):
        cfg = GigaEvoConfig(
            platform_base_url="https://plat.test",
            api_key="sk-cfg",
            timeout=5.0,
        )
        c = PlatformClient.from_config(cfg)
        assert c._base_url == "https://plat.test"
        assert c._api_key == "sk-cfg"

    def test_fallback_when_platform_url_none(self):
        """``GigaEvoConfig.platform_base_url`` is None by default;
        the client should land on the documented localhost port."""
        c = PlatformClient.from_config(GigaEvoConfig())
        assert c._base_url == "http://localhost:8001"


# ---------------------------------------------------------------------------
# Method → URL mapping (via respx mocked httpx layer)
# ---------------------------------------------------------------------------


BASE = "http://localhost:8001"


@pytest.fixture
def client():
    return PlatformClient()


class TestPlatformClientReadEndpoints:
    @respx.mock
    def test_health(self, client):
        route = respx.get(f"{BASE}/api/v1/status").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        assert client.health() == {"status": "ok"}
        assert route.called

    @respx.mock
    def test_list_experiments(self, client):
        respx.get(f"{BASE}/api/v1/experiments").mock(
            return_value=httpx.Response(200, json=[{"id": "exp-1"}])
        )
        assert client.list_experiments() == [{"id": "exp-1"}]

    @respx.mock
    def test_get_experiment(self, client):
        respx.get(f"{BASE}/api/v1/experiments/exp-42").mock(
            return_value=httpx.Response(200, json={"id": "exp-42"})
        )
        assert client.get_experiment("exp-42") == {"id": "exp-42"}

    @respx.mock
    def test_get_status(self, client):
        respx.get(f"{BASE}/api/v1/experiments/exp-42/status").mock(
            return_value=httpx.Response(200, json={"state": "running"})
        )
        assert client.get_status("exp-42") == {"state": "running"}

    @respx.mock
    def test_get_results(self, client):
        respx.get(f"{BASE}/api/v1/experiments/exp-42/results").mock(
            return_value=httpx.Response(200, json={"score": 0.91})
        )
        assert client.get_results("exp-42") == {"score": 0.91}


class TestPlatformClientMutators:
    @respx.mock
    def test_start_experiment(self, client):
        route = respx.post(
            f"{BASE}/api/v1/experiments/exp-42/start"
        ).mock(return_value=httpx.Response(200, json={"state": "running"}))
        assert client.start_experiment("exp-42") == {"state": "running"}
        assert route.called

    @respx.mock
    def test_stop_experiment(self, client):
        respx.post(f"{BASE}/api/v1/experiments/exp-42/stop").mock(
            return_value=httpx.Response(200, json={"state": "stopped"})
        )
        assert client.stop_experiment("exp-42") == {"state": "stopped"}

    @respx.mock
    def test_create_chain_experiment_forwards_spec(self, client):
        captured = {}

        def _handler(request):
            import json
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"experiment_id": "exp-99"})

        respx.post(f"{BASE}/api/v1/experiments/chains").mock(
            side_effect=_handler
        )
        spec = {"chain_id": "c1", "iterations": 10}
        result = client.create_chain_experiment(spec)
        assert result == {"experiment_id": "exp-99"}
        assert captured["body"] == spec

    @respx.mock
    def test_create_evolution_forwards_spec(self, client):
        captured = {}

        def _handler(request):
            import json
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"evolution_id": "ev-1"})

        respx.post(f"{BASE}/api/v1/evolutions").mock(side_effect=_handler)
        spec = {"target_chain_id": "c1", "budget": 5}
        assert client.create_evolution(spec) == {"evolution_id": "ev-1"}
        assert captured["body"] == spec


class TestPlatformClientErrorPropagation:
    @respx.mock
    def test_404_raises_status_error(self, client):
        respx.get(f"{BASE}/api/v1/experiments/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        with pytest.raises(httpx.HTTPStatusError) as exc:
            client.get_experiment("missing")
        assert exc.value.response.status_code == 404


# ---------------------------------------------------------------------------
# Evolution inspection (CARE PREPARE §2.6, Platform §4.2 / §4.4)
# ---------------------------------------------------------------------------


class TestGetEvolution:
    @respx.mock
    def test_get_evolution_returns_state(self, client):
        payload = {
            "evolution_id": "ev-1",
            "status": "running",
            "generation": 3,
            "best_fitness": 0.87,
        }
        route = respx.get(f"{BASE}/api/v1/evolutions/ev-1").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.get_evolution("ev-1") == payload
        assert route.called

    @respx.mock
    def test_get_evolution_404_raises(self, client):
        respx.get(f"{BASE}/api/v1/evolutions/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        with pytest.raises(httpx.HTTPStatusError) as exc:
            client.get_evolution("missing")
        assert exc.value.response.status_code == 404


class TestListIndividuals:
    @respx.mock
    def test_list_individuals_returns_list(self, client):
        payload = [
            {"individual_id": "ind-1", "fitness": 0.91, "generation": 3},
            {"individual_id": "ind-2", "fitness": 0.83, "generation": 3},
        ]
        route = respx.get(
            f"{BASE}/api/v1/evolutions/ev-1/individuals"
        ).mock(return_value=httpx.Response(200, json=payload))
        assert client.list_individuals("ev-1") == payload
        assert route.called

    @respx.mock
    def test_list_individuals_empty_population(self, client):
        respx.get(f"{BASE}/api/v1/evolutions/ev-empty/individuals").mock(
            return_value=httpx.Response(200, json=[])
        )
        assert client.list_individuals("ev-empty") == []


class TestAcceptIndividual:
    @respx.mock
    def test_accept_individual_forwards_id_in_body(self, client):
        captured = {}

        def _handler(request):
            import json

            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"evolution_id": "ev-1", "accepted_individual": "ind-7"},
            )

        respx.post(f"{BASE}/api/v1/evolutions/ev-1/accept").mock(
            side_effect=_handler
        )
        result = client.accept_individual("ev-1", "ind-7")
        assert result == {
            "evolution_id": "ev-1",
            "accepted_individual": "ind-7",
        }
        assert captured["body"] == {"individual_id": "ind-7"}

    @respx.mock
    def test_accept_individual_idempotent_same_id(self, client):
        """Same individual id twice returns the same shape — the SDK
        is a passthrough; idempotency is a server contract that the
        SDK doesn't need to enforce, but we verify a second call
        doesn't blow up locally."""
        respx.post(f"{BASE}/api/v1/evolutions/ev-1/accept").mock(
            return_value=httpx.Response(
                200,
                json={"evolution_id": "ev-1", "accepted_individual": "ind-7"},
            )
        )
        first = client.accept_individual("ev-1", "ind-7")
        second = client.accept_individual("ev-1", "ind-7")
        assert first == second

    @respx.mock
    def test_accept_individual_409_on_switch(self, client):
        """Switching to a different id after a prior accept yields
        ``409 Conflict``. The SDK surfaces that as
        ``httpx.HTTPStatusError`` so callers can read the
        currently-accepted id off ``exc.response.json()``."""
        respx.post(f"{BASE}/api/v1/evolutions/ev-1/accept").mock(
            return_value=httpx.Response(
                409,
                json={
                    "detail": "already accepted",
                    "accepted_individual": "ind-3",
                },
            )
        )
        with pytest.raises(httpx.HTTPStatusError) as exc:
            client.accept_individual("ev-1", "ind-7")
        assert exc.value.response.status_code == 409
        assert exc.value.response.json()["accepted_individual"] == "ind-3"

    @respx.mock
    def test_accept_individual_sends_api_key(self):
        c = PlatformClient(api_key="sk-evo-accept")
        captured = {}

        def _handler(request):
            captured["header"] = request.headers.get("X-API-Key")
            return httpx.Response(
                200,
                json={"evolution_id": "ev-1", "accepted_individual": "ind-7"},
            )

        respx.post(f"{BASE}/api/v1/evolutions/ev-1/accept").mock(
            side_effect=_handler
        )
        c.accept_individual("ev-1", "ind-7")
        assert captured["header"] == "sk-evo-accept"


class TestPlatformClientAuthHeader:
    @respx.mock
    def test_api_key_sent_on_every_request(self):
        client = PlatformClient(api_key="sk-auth-test")
        captured = {}

        def _handler(request):
            captured["header"] = request.headers.get("X-API-Key")
            return httpx.Response(200, json={"status": "ok"})

        respx.get(f"{BASE}/api/v1/status").mock(side_effect=_handler)
        client.health()
        assert captured["header"] == "sk-auth-test"


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------


class TestStreamEvents:
    @respx.mock
    def test_yields_parsed_dicts(self, client):
        sse_body = (
            "data: {\"event\": \"step_complete\", \"step\": 1}\n"
            "\n"
            "data: {\"event\": \"step_complete\", \"step\": 2}\n"
            "\n"
        )
        respx.get(f"{BASE}/api/v1/experiments/exp-42/events").mock(
            return_value=httpx.Response(200, text=sse_body)
        )
        events = list(client.stream_events("exp-42"))
        assert events == [
            {"event": "step_complete", "step": 1},
            {"event": "step_complete", "step": 2},
        ]

    @respx.mock
    def test_skips_empty_data_frames(self, client):
        sse_body = (
            "data: \n"
            "\n"
            "data: {\"k\": 1}\n"
            "\n"
        )
        respx.get(f"{BASE}/api/v1/experiments/exp-42/events").mock(
            return_value=httpx.Response(200, text=sse_body)
        )
        events = list(client.stream_events("exp-42"))
        assert events == [{"k": 1}]


# ---------------------------------------------------------------------------
# GigaEvoSuite
# ---------------------------------------------------------------------------


class TestGigaEvoSuiteConstruction:
    def test_default_construction(self):
        suite = GigaEvoSuite()
        assert isinstance(suite.memory, GigaEvoClient)
        assert isinstance(suite.platform, PlatformClient)
        assert suite.memory._base_url == "http://localhost:8000"
        assert suite.platform._base_url == "http://localhost:8001"

    def test_two_separate_http_clients(self):
        """Each sub-client owns its own httpx.Client pointed at a
        different backend — that's the whole reason composition was
        chosen over the TODO's literal multiple-inheritance sketch."""
        suite = GigaEvoSuite()
        assert suite.memory._http is not suite.platform._http

    def test_shared_api_key(self):
        suite = GigaEvoSuite(api_key="sk-shared")
        assert suite.memory._http.headers.get("X-API-Key") == "sk-shared"
        assert suite.platform._http.headers.get("X-API-Key") == "sk-shared"

    def test_explicit_urls(self):
        suite = GigaEvoSuite(
            memory_base_url="https://memory.example.com",
            platform_base_url="https://plat.example.com",
        )
        assert suite.memory._base_url == "https://memory.example.com"
        assert suite.platform._base_url == "https://plat.example.com"


class TestGigaEvoSuiteFromConfig:
    def test_from_config_round_trips_both_urls(self):
        cfg = GigaEvoConfig(
            memory_base_url="https://memory.test",
            platform_base_url="https://plat.test",
            api_key="sk-cfg",
        )
        suite = GigaEvoSuite.from_config(cfg)
        assert suite.memory._base_url == "https://memory.test"
        assert suite.platform._base_url == "https://plat.test"

    def test_from_config_fallback_when_platform_url_none(self):
        """``GigaEvoConfig.platform_base_url`` is None by default."""
        suite = GigaEvoSuite.from_config(GigaEvoConfig())
        assert suite.platform._base_url == "http://localhost:8001"

    def test_from_config_shares_api_key(self):
        cfg = GigaEvoConfig(api_key="sk-from-config")
        suite = GigaEvoSuite.from_config(cfg)
        assert suite.memory._http.headers.get("X-API-Key") == "sk-from-config"
        assert suite.platform._http.headers.get("X-API-Key") == "sk-from-config"


class TestGigaEvoSuiteLifecycle:
    def test_context_manager(self):
        with GigaEvoSuite() as suite:
            assert isinstance(suite.memory, GigaEvoClient)
        # After __exit__ both http clients are closed; httpx exposes
        # this state via the private ``_state`` attribute / is_closed
        # property. Use the public ``is_closed`` flag for the check.
        assert suite.memory._http.is_closed
        assert suite.platform._http.is_closed

    def test_close_closes_both(self):
        suite = GigaEvoSuite()
        suite.close()
        assert suite.memory._http.is_closed
        assert suite.platform._http.is_closed


# ---------------------------------------------------------------------------
# Legacy shim path
# ---------------------------------------------------------------------------


class TestLegacyImports:
    def test_platform_client_via_legacy_shim(self):
        """Both new classes are reachable via the legacy
        ``gigaevo_memory`` package too."""
        from gigaevo_memory import PlatformClient as Legacy
        from gigaevo_client import PlatformClient as Canonical
        assert Legacy is Canonical

    def test_suite_via_legacy_shim(self):
        from gigaevo_memory import GigaEvoSuite as Legacy
        from gigaevo_client import GigaEvoSuite as Canonical
        assert Legacy is Canonical

    def test_submodule_access_via_legacy_shim(self):
        from gigaevo_memory.platform import PlatformClient as Legacy
        from gigaevo_client.platform import PlatformClient as Canonical
        assert Legacy is Canonical
