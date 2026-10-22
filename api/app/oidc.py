"""OIDC bearer-token verification for SSO deployments (TODO §3 P3).

Validates ``Authorization: Bearer <jwt>`` against the deployment's
OIDC provider:

  1. Fetch the issuer's JWKS (JSON Web Key Set) — cached in-process
     with a TTL so we don't round-trip to the provider on every
     request.
  2. Decode + verify the JWT's signature against the matching JWK.
  3. Enforce ``iss`` / ``aud`` / ``exp`` claims with a small clock-skew
     leeway.
  4. Project the verified claims onto an :class:`AuthContext`:
     ``settings.oidc_sub_claim`` → ``owner``,
     ``settings.oidc_scopes_claim`` → ``scopes``.

Scopes mapping accepts both string forms (space-separated, per OAuth2)
and list-of-strings (some providers like Auth0 emit lists).

The module is configuration-driven — when ``settings.oidc_enabled`` is
False the verifier never instantiates and the call sites short-circuit.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError

from .config import settings


class OIDCError(Exception):
    """Raised when an OIDC token fails verification.

    The auth dependency translates this into ``401 Unauthorized``.
    """


@dataclass
class _CachedJWKS:
    fetched_at: float
    keys: Any  # authlib.jose.JsonWebKey — type left loose for forward-compat


class JWKSCache:
    """Thread-safe TTL cache for an OIDC provider's JWKS.

    Pulls the keyset on first use, then refreshes after
    ``settings.oidc_jwks_cache_ttl_seconds``. A fetch failure does NOT
    clear an existing cache — we keep the last good keys and let the
    next request retry. Tokens signed with a key not in the current
    cache trigger a forced refresh exactly once per request to handle
    legitimate key rotation.
    """

    def __init__(self, jwks_uri: str, ttl_seconds: int):
        self._jwks_uri = jwks_uri
        self._ttl = ttl_seconds
        self._cached: _CachedJWKS | None = None
        self._lock = threading.Lock()
        # Allows tests + callers to swap the fetch (e.g. for offline
        # signing in unit tests).
        self._fetcher = self._fetch_jwks_over_http

    def get(self, *, force_refresh: bool = False) -> Any:
        with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._cached is not None
                and now - self._cached.fetched_at < self._ttl
            ):
                return self._cached.keys
            try:
                keys = self._fetcher(self._jwks_uri)
            except Exception as exc:
                if self._cached is not None:
                    # Stale-but-usable: keep serving old keys rather
                    # than failing every request during a transient
                    # provider outage.
                    return self._cached.keys
                raise OIDCError(f"Failed to fetch JWKS from {self._jwks_uri}: {exc}") from exc
            self._cached = _CachedJWKS(fetched_at=now, keys=keys)
            return keys

    @staticmethod
    def _fetch_jwks_over_http(jwks_uri: str) -> Any:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(jwks_uri)
            response.raise_for_status()
            return JsonWebKey.import_key_set(response.json())


@dataclass
class VerifiedClaims:
    """Result of a successful token verification.

    Exposed so the auth dependency + tests can construct an
    :class:`AuthContext` from the claim shape without re-running the
    verifier.
    """

    sub: str
    scopes: frozenset[str]
    raw: dict[str, Any]


class OIDCVerifier:
    """Verifies OIDC bearer tokens against the configured provider."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | None,
        jwks_cache: JWKSCache,
        sub_claim: str,
        scopes_claim: str,
        leeway_seconds: int,
    ):
        self._issuer = issuer
        self._audience = audience
        self._jwks_cache = jwks_cache
        self._sub_claim = sub_claim
        self._scopes_claim = scopes_claim
        self._leeway = leeway_seconds

    def verify(self, token: str) -> VerifiedClaims:
        """Validate ``token`` and return its projected claims.

        Raises :class:`OIDCError` for any verification failure
        (signature mismatch, expired, wrong issuer/audience, malformed
        token).
        """
        if not token:
            raise OIDCError("Empty bearer token")

        try:
            claims = jwt.decode(token, self._jwks_cache.get())
        except JoseError as exc:
            # The signing key may have rotated since we last cached.
            # Force a JWKS refresh and retry exactly once before giving
            # up — covers the common operator rotation case.
            try:
                claims = jwt.decode(token, self._jwks_cache.get(force_refresh=True))
            except JoseError as exc2:
                raise OIDCError(f"Token signature invalid: {exc2}") from exc2
            except Exception as exc2:
                raise OIDCError(f"Token verification failed: {exc2}") from exc2
            del exc

        validate_options = {
            "iss": {"essential": True, "value": self._issuer},
            "exp": {"essential": True},
        }
        if self._audience is not None:
            validate_options["aud"] = {"essential": True, "value": self._audience}

        claims.options = validate_options
        try:
            claims.validate(leeway=self._leeway)
        except JoseError as exc:
            raise OIDCError(f"Token claim validation failed: {exc}") from exc

        sub = claims.get(self._sub_claim)
        if not isinstance(sub, str) or not sub:
            raise OIDCError(
                f"Token missing required {self._sub_claim!r} claim"
            )
        return VerifiedClaims(
            sub=sub,
            scopes=_normalise_scopes(claims.get(self._scopes_claim)),
            raw=dict(claims),
        )


def _normalise_scopes(raw: Any) -> frozenset[str]:
    """Coerce a token's scopes claim into a ``frozenset[str]``.

    Accepts the two shapes providers emit in the wild:

    * **Space-separated string** (`"read:any write:any"`) — the OAuth2
      standard for the ``scope`` claim.
    * **List of strings** (`["read:any", "write:any"]`) — common when
      the claim is named ``scopes`` instead (Auth0, Keycloak).

    Any other shape (None, dict, etc.) yields an empty set rather than
    raising — a missing scopes claim is legal, scope checks at the
    route level will then 403 the caller for any non-anonymous gate.
    """
    if isinstance(raw, str):
        return frozenset(tok for tok in raw.split() if tok)
    if isinstance(raw, list):
        return frozenset(str(tok) for tok in raw if tok)
    return frozenset()


_VERIFIER_SINGLETON: OIDCVerifier | None = None
_SINGLETON_LOCK = threading.Lock()


def get_oidc_verifier() -> OIDCVerifier | None:
    """Return the process-wide :class:`OIDCVerifier`, or ``None`` when
    OIDC is disabled.

    Builds the verifier (and its JWKS cache) lazily on first use so
    deployments without OIDC pay zero cost. Subsequent calls return
    the same instance; the cache state is shared across requests.
    """
    if not settings.oidc_enabled:
        return None
    global _VERIFIER_SINGLETON
    if _VERIFIER_SINGLETON is not None:
        return _VERIFIER_SINGLETON
    with _SINGLETON_LOCK:
        if _VERIFIER_SINGLETON is not None:
            return _VERIFIER_SINGLETON
        if not settings.oidc_issuer:
            raise OIDCError(
                "OIDC_ENABLED is true but OIDC_ISSUER is unset — provide an issuer URL."
            )
        jwks_uri = settings.oidc_jwks_uri or (
            settings.oidc_issuer.rstrip("/") + "/.well-known/jwks.json"
        )
        _VERIFIER_SINGLETON = OIDCVerifier(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_cache=JWKSCache(jwks_uri, settings.oidc_jwks_cache_ttl_seconds),
            sub_claim=settings.oidc_sub_claim,
            scopes_claim=settings.oidc_scopes_claim,
            leeway_seconds=settings.oidc_leeway_seconds,
        )
        return _VERIFIER_SINGLETON


def reset_oidc_verifier() -> None:
    """Drop the cached verifier — used by tests + by config reloads.

    Triggers a fresh build (and JWKS fetch) on the next
    :func:`get_oidc_verifier` call.
    """
    global _VERIFIER_SINGLETON
    with _SINGLETON_LOCK:
        _VERIFIER_SINGLETON = None
