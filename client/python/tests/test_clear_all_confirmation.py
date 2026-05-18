"""Tests for ``MemoryClient.clear_all`` confirmation gate."""

import httpx
import pytest
import respx

from gigaevo_memory import ConflictError, MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestClientConfirmGate:
    def test_confirm_false_raises_before_network(self, client):
        """Default `confirm=False` must NEVER reach the wire."""
        with respx.mock(assert_all_called=False) as mock:
            mock.post("http://test-api:8000/v1/maintenance/clear-all").mock(
                return_value=httpx.Response(200, json={"deleted": {}})
            )
            with pytest.raises(ValueError, match="confirm=True"):
                client.clear_all()
            with pytest.raises(ValueError, match="confirm=True"):
                client.clear_all(entity_type="chain")
            # Server saw zero traffic.
            assert len(mock.calls) == 0

    def test_confirm_true_sends_header(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/maintenance/clear-all").mock(
                return_value=httpx.Response(200, json={"deleted": {"chain": 7}})
            )
            out = client.clear_all(confirm=True)
        assert out == {"chain": 7}
        sent_header = route.calls.last.request.headers.get("X-Confirm")
        assert sent_header == "yes-i-really-mean-it"

    def test_entity_type_passed_through(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/maintenance/clear-all").mock(
                return_value=httpx.Response(200, json={"deleted": {"chain": 0}})
            )
            client.clear_all(entity_type="chain", confirm=True)
        # entity_type lands in the query string.
        assert b"entity_type=chain" in route.calls.last.request.url.query

    def test_server_412_surfaces_as_conflict(self, client):
        """If the server rejects the header for some reason, raise."""
        with respx.mock:
            respx.post("http://test-api:8000/v1/maintenance/clear-all").mock(
                return_value=httpx.Response(
                    412, json={"detail": "Precondition Failed: bad token"}
                )
            )
            with pytest.raises(ConflictError):
                client.clear_all(confirm=True)

    def test_constant_matches_server_contract(self):
        """The sentinel is part of the cross-package API contract.

        Server lives in ``api/app/routers/entities.py`` —
        ``CLEAR_ALL_CONFIRM_TOKEN = "yes-i-really-mean-it"``. This
        client SDK package can't import it directly (the API package
        isn't a runtime dep), so we hard-code the same phrase here.

        Server-side test ``test_clear_all_confirmation.py::
        TestConfirmTokenConstantStable`` asserts the same literal.
        Renames to the constant must update **both** sides.
        """
        assert MemoryClient.CLEAR_ALL_CONFIRM_TOKEN == "yes-i-really-mean-it"
