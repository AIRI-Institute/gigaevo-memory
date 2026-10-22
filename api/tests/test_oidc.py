"""Tests for OIDC bearer-token integration (TODO §3 P3).

Four layers:
  1. Pure helpers — bearer-header parsing, scope normalisation.
  2. ``JWKSCache`` — TTL caching, stale-on-failure fallback,
     forced-refresh path.
  3. ``OIDCVerifier`` end-to-end against an in-test RSA keypair and a
     real JWT minted by `authlib.jose.jwt.encode`.
  4. ``require_api_key`` dependency — Bearer-beats-API-Key precedence,
     401 on bad token, opt-in fallthrough, strict-mode behaviour.

No live OIDC provider is needed — the test generates its own keypair,
patches the JWKS cache fetcher, and mints JWTs with the same authlib
machinery the production verifier uses.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth, oidc
from app.config import settings


# ---------------------------------------------------------------------------
# Test keypair fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate an RSA keypair once per test module.

    Returns ``(private_pem, public_jwk)`` where ``private_pem`` is the
    bytes used to sign tokens and ``public_jwk`` is a JsonWebKey
    suitable for stuffing into a fake JWKS endpoint.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_jwk = JsonWebKey.import_key(public_pem, {"kty": "RSA", "use": "sig", "kid": "test-kid"})
    return private_pem, public_jwk


def _mint(private_pem: bytes, claims: dict, *, kid: str = "test-kid") -> str:
    """Sign a JWT with the test keypair. Adds default `iat` if absent."""
    header = {"alg": "RS256", "kid": kid}
    payload = {"iat": int(time.time()), **claims}
    token_bytes = jwt.encode(header, payload, private_pem)
    return token_bytes.decode("ascii") if isinstance(token_bytes, bytes) else token_bytes


@pytest.fixture(autouse=True)
def reset_state():
    """Each test starts from a clean OIDC config + verifier cache."""
    snapshot = {
        "oidc_enabled": settings.oidc_enabled,
        "oidc_issuer": settings.oidc_issuer,
        "oidc_audience": settings.oidc_audience,
        "oidc_jwks_uri": settings.oidc_jwks_uri,
        "oidc_sub_claim": settings.oidc_sub_claim,
        "oidc_scopes_claim": settings.oidc_scopes_claim,
        "oidc_leeway_seconds": settings.oidc_leeway_seconds,
        "auth_required": settings.auth_required,
    }
    oidc.reset_oidc_verifier()
    yield
    for k, v in snapshot.items():
        setattr(settings, k, v)
    oidc.reset_oidc_verifier()


@pytest.fixture
def configured_oidc(rsa_keypair):
    """Configure OIDC against the test keypair + patch the JWKS fetcher
    so the verifier doesn't try to hit a real network endpoint."""
    _, public_jwk = rsa_keypair
    settings.oidc_enabled = True
    settings.oidc_issuer = "https://test.gigaevo.io/realms/test"
    settings.oidc_audience = "gigaevo-memory"
    settings.oidc_jwks_uri = "https://test.gigaevo.io/jwks.json"

    verifier = oidc.get_oidc_verifier()
    assert verifier is not None

    # Pretend the network fetch returned a JWKS containing our test key.
    def fake_fetcher(_uri):
        return JsonWebKey.import_key_set({"keys": [public_jwk.as_dict()]})

    verifier._jwks_cache._fetcher = fake_fetcher  # type: ignore[attr-defined]
    return verifier


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestBearerExtraction:
    def test_well_formed_token(self):
        assert auth._extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"

    def test_case_insensitive_scheme(self):
        assert auth._extract_bearer_token("bearer abc") == "abc"
        assert auth._extract_bearer_token("BEARER abc") == "abc"

    def test_missing_returns_none(self):
        assert auth._extract_bearer_token(None) is None
        assert auth._extract_bearer_token("") is None

    def test_non_bearer_scheme_returns_none(self):
        assert auth._extract_bearer_token("Basic dXNlcjpwYXNz") is None

    def test_empty_token_returns_none(self):
        assert auth._extract_bearer_token("Bearer ") is None
        assert auth._extract_bearer_token("Bearer    ") is None


class TestScopeNormalisation:
    def test_space_separated_string(self):
        assert oidc._normalise_scopes("read:any write:any") == frozenset(
            {"read:any", "write:any"}
        )

    def test_empty_string(self):
        assert oidc._normalise_scopes("") == frozenset()

    def test_list_of_strings(self):
        assert oidc._normalise_scopes(["read:any", "evolve"]) == frozenset(
            {"read:any", "evolve"}
        )

    def test_none(self):
        assert oidc._normalise_scopes(None) == frozenset()

    def test_unknown_shape(self):
        # Dict shouldn't crash; just yields empty.
        assert oidc._normalise_scopes({"unexpected": True}) == frozenset()


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------


class TestJWKSCache:
    def test_caches_first_fetch(self):
        cache = oidc.JWKSCache("http://test/jwks", ttl_seconds=60)
        calls = {"n": 0}

        def fetcher(_uri):
            calls["n"] += 1
            return MagicMock(name="keys")

        cache._fetcher = fetcher  # type: ignore[attr-defined]

        keys_1 = cache.get()
        keys_2 = cache.get()
        assert keys_1 is keys_2
        assert calls["n"] == 1

    def test_force_refresh_bypasses_cache(self):
        cache = oidc.JWKSCache("http://test/jwks", ttl_seconds=60)
        calls = {"n": 0}

        def fetcher(_uri):
            calls["n"] += 1
            return MagicMock(name=f"keys-{calls['n']}")

        cache._fetcher = fetcher  # type: ignore[attr-defined]
        cache.get()
        cache.get(force_refresh=True)
        assert calls["n"] == 2

    def test_stale_keys_kept_on_fetch_failure(self):
        cache = oidc.JWKSCache("http://test/jwks", ttl_seconds=0)
        good = MagicMock(name="good")

        def fetcher(_uri):
            return good

        cache._fetcher = fetcher  # type: ignore[attr-defined]
        keys_1 = cache.get()
        assert keys_1 is good

        def broken(_uri):
            raise RuntimeError("network down")

        cache._fetcher = broken  # type: ignore[attr-defined]
        # TTL=0 means the next get() would refresh, but the fetcher
        # raises — we should fall back to the stale cache.
        keys_2 = cache.get()
        assert keys_2 is good

    def test_initial_fetch_failure_raises(self):
        cache = oidc.JWKSCache("http://test/jwks", ttl_seconds=60)

        def broken(_uri):
            raise RuntimeError("DNS")

        cache._fetcher = broken  # type: ignore[attr-defined]
        with pytest.raises(oidc.OIDCError, match="Failed to fetch JWKS"):
            cache.get()


# ---------------------------------------------------------------------------
# OIDCVerifier end-to-end
# ---------------------------------------------------------------------------


class TestOIDCVerifier:
    def test_valid_token(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "alice@example.com",
            "exp": int(time.time()) + 3600,
            "scope": "read:any evolve",
        })
        verified = configured_oidc.verify(token)
        assert verified.sub == "alice@example.com"
        assert verified.scopes == frozenset({"read:any", "evolve"})

    def test_expired_token_rejected(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "alice",
            "exp": int(time.time()) - 3600,  # expired an hour ago
        })
        with pytest.raises(oidc.OIDCError, match="claim validation failed"):
            configured_oidc.verify(token)

    def test_wrong_issuer_rejected(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://impostor.example.com",
            "aud": "gigaevo-memory",
            "sub": "alice",
            "exp": int(time.time()) + 3600,
        })
        with pytest.raises(oidc.OIDCError, match="claim validation failed"):
            configured_oidc.verify(token)

    def test_wrong_audience_rejected(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "other-service",
            "sub": "alice",
            "exp": int(time.time()) + 3600,
        })
        with pytest.raises(oidc.OIDCError, match="claim validation failed"):
            configured_oidc.verify(token)

    def test_missing_sub_rejected(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "exp": int(time.time()) + 3600,
        })
        with pytest.raises(oidc.OIDCError, match="missing required"):
            configured_oidc.verify(token)

    def test_wrong_signature_rejected(self, configured_oidc):
        # Mint a token with a *different* key, expecting verification
        # to fail against the configured one.
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        token = _mint(other_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "alice",
            "exp": int(time.time()) + 3600,
        }, kid="test-kid")  # claim the kid the cache knows about
        with pytest.raises(oidc.OIDCError):
            configured_oidc.verify(token)

    def test_scopes_as_list_claim(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        # Reconfigure to read the `scopes` (plural) claim — Auth0 style.
        configured_oidc._scopes_claim = "scopes"  # type: ignore[attr-defined]
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "alice",
            "exp": int(time.time()) + 3600,
            "scopes": ["write:any", "delete:any"],
        })
        verified = configured_oidc.verify(token)
        assert verified.scopes == frozenset({"write:any", "delete:any"})

    def test_no_audience_required(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        # Drop the audience requirement — some providers (e.g. ID
        # tokens without an explicit aud) need this.
        configured_oidc._audience = None  # type: ignore[attr-defined]
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "sub": "bob",
            "exp": int(time.time()) + 3600,
        })
        verified = configured_oidc.verify(token)
        assert verified.sub == "bob"

    def test_empty_token_rejected(self, configured_oidc):
        with pytest.raises(oidc.OIDCError, match="Empty bearer token"):
            configured_oidc.verify("")


# ---------------------------------------------------------------------------
# Verifier singleton + reset
# ---------------------------------------------------------------------------


class TestVerifierSingleton:
    def test_disabled_returns_none(self):
        settings.oidc_enabled = False
        assert oidc.get_oidc_verifier() is None

    def test_returns_same_instance(self, configured_oidc):
        v1 = oidc.get_oidc_verifier()
        v2 = oidc.get_oidc_verifier()
        assert v1 is v2 is configured_oidc

    def test_reset_drops_singleton(self, configured_oidc):
        oidc.reset_oidc_verifier()
        # Reconfigure with a fresh fetcher so the new singleton has
        # working JWKS. The fixture-installed verifier is gone.
        v = oidc.get_oidc_verifier()
        assert v is not configured_oidc

    def test_missing_issuer_raises(self):
        settings.oidc_enabled = True
        settings.oidc_issuer = None
        with pytest.raises(oidc.OIDCError, match="OIDC_ISSUER is unset"):
            oidc.get_oidc_verifier()

    def test_jwks_uri_defaults_to_well_known(self):
        settings.oidc_enabled = True
        settings.oidc_issuer = "https://issuer.example.com/realm"
        settings.oidc_jwks_uri = None
        v = oidc.get_oidc_verifier()
        assert v is not None
        assert (
            v._jwks_cache._jwks_uri  # type: ignore[attr-defined]
            == "https://issuer.example.com/realm/.well-known/jwks.json"
        )


# ---------------------------------------------------------------------------
# Auth dependency end-to-end
# ---------------------------------------------------------------------------


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class TestAuthDependency:
    def test_valid_bearer_returns_context(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "alice@example.com",
            "exp": int(time.time()) + 3600,
            "scope": "read:any",
        })
        ctx = _run(auth.require_api_key(
            x_api_key=None,
            authorization=f"Bearer {token}",
            db=MagicMock(),
        ))
        assert ctx.owner == "alice@example.com"
        assert "read:any" in ctx.scopes
        # JWT-issued contexts must NOT read as anonymous.
        assert not ctx.is_anonymous

    def test_invalid_bearer_401(self, configured_oidc):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as ei:
            _run(auth.require_api_key(
                x_api_key=None,
                authorization="Bearer this.is.not.a.real.jwt",
                db=MagicMock(),
            ))
        assert ei.value.status_code == 401
        assert ei.value.headers["WWW-Authenticate"] == "Bearer"

    def test_bearer_when_oidc_disabled_401(self):
        from fastapi import HTTPException

        settings.oidc_enabled = False
        with pytest.raises(HTTPException) as ei:
            _run(auth.require_api_key(
                x_api_key=None,
                authorization="Bearer some.token.here",
                db=MagicMock(),
            ))
        assert ei.value.status_code == 401
        assert "OIDC is disabled" in ei.value.detail

    def test_bearer_beats_x_api_key(self, rsa_keypair, configured_oidc):
        """When both schemes are supplied, the Bearer token wins —
        the X-API-Key path must not even be consulted."""
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "from-bearer",
            "exp": int(time.time()) + 3600,
        })
        # If the X-API-Key path were consulted, this MagicMock would
        # fail (ApiKeyService.verify_key would explode on a MagicMock
        # session). The test passing demonstrates it isn't touched.
        ctx = _run(auth.require_api_key(
            x_api_key="should-not-be-used",
            authorization=f"Bearer {token}",
            db=MagicMock(),
        ))
        assert ctx.owner == "from-bearer"

    def test_no_auth_opt_in_returns_anonymous(self):
        settings.auth_required = False
        ctx = _run(auth.require_api_key(
            x_api_key=None,
            authorization=None,
            db=MagicMock(),
        ))
        assert ctx.is_anonymous
        assert ctx.owner == settings.auth_anonymous_owner

    def test_no_auth_strict_mode_401(self):
        from fastapi import HTTPException

        settings.auth_required = True
        with pytest.raises(HTTPException) as ei:
            _run(auth.require_api_key(
                x_api_key=None,
                authorization=None,
                db=MagicMock(),
            ))
        assert ei.value.status_code == 401
        # Helpful WWW-Authenticate listing both schemes.
        assert "Bearer" in ei.value.headers["WWW-Authenticate"]
        assert "X-API-Key" in ei.value.headers["WWW-Authenticate"]

    def test_bearer_jti_used_as_key_id(self, rsa_keypair, configured_oidc):
        private_pem, _ = rsa_keypair
        token = _mint(private_pem, {
            "iss": "https://test.gigaevo.io/realms/test",
            "aud": "gigaevo-memory",
            "sub": "alice",
            "exp": int(time.time()) + 3600,
            "jti": "token-id-7",
        })
        ctx = _run(auth.require_api_key(
            x_api_key=None,
            authorization=f"Bearer {token}",
            db=MagicMock(),
        ))
        assert ctx.key_id == "token-id-7"
