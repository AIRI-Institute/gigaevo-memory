"""FastAPI dependency for X-API-Key authentication (P1 §3).

Wire onto a router via::

    from app.auth import require_api_key, AuthContext

    @router.post("/protected")
    async def handler(auth: AuthContext = Depends(require_api_key)):
        ...

Dual-mode behaviour driven by ``settings.auth_required``:

* **Strict mode** (``auth_required=True``, production): missing /
  empty / invalid / revoked / expired keys all return
  ``401 Unauthorized``. The dependency always yields a real
  :class:`AuthContext`.

* **Opt-in mode** (``auth_required=False``, default for dev/CI):
  missing or empty headers yield an *anonymous* :class:`AuthContext`
  (``owner=settings.auth_anonymous_owner``, empty scope set,
  ``key_id=""``). Routes can still read ``auth.owner`` and
  ``auth.scopes`` uniformly — protected operations gated by
  ``auth.require_scope(...)`` will 403 the anonymous caller because
  it carries no scopes. **Invalid headers still 401** even in opt-in
  mode, so a leaked-then-revoked key can't downgrade silently to
  anonymous.

Routes consume :class:`AuthContext` to scope writes
(``namespace = auth.owner``), gate sensitive operations
(``auth.require_scope("evolve")``), and tag audit logs.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db.session import get_db
from .services.api_key_service import ApiKeyService

# ---------------------------------------------------------------------------
# Scope vocabulary (P2 §3) — canonical strings that may appear in
# ``ApiKey.scopes`` and be gated via ``AuthContext.require_scope(...)``.
#
# Scopes follow the ``namespace:action`` shape:
#
#   read:any        — read across namespaces (default is own-namespace).
#   write:any       — write to namespaces other than ``auth.owner``.
#   delete:any      — soft-delete entities outside the owner's namespace.
#   clear:all       — destructive bulk maintenance (``/maintenance/clear-all``).
#   admin:keys      — manage API keys for other principals.
#   evolve          — promote / pin / mutate the ``evolved`` channel.
#                     (Reserved — no endpoint gates it yet; iter #28 tests
#                     reference it as a probe for the scope mechanism.)
#
# These constants exist so call-sites can ``require_scope(SCOPE_CLEAR_ALL)``
# instead of stringly-typing ``"clear:all"``. ``ALL_SCOPES`` is the
# authoritative inventory — anything outside it is treated as a free-form
# custom scope by ``has_scope``/``require_scope`` (forward compat for
# deployment-specific tags like ``"finance-team"``).
# ---------------------------------------------------------------------------

SCOPE_READ_ANY: str = "read:any"
SCOPE_WRITE_ANY: str = "write:any"
SCOPE_DELETE_ANY: str = "delete:any"
SCOPE_CLEAR_ALL: str = "clear:all"
SCOPE_ADMIN_KEYS: str = "admin:keys"
SCOPE_EVOLVE: str = "evolve"

ALL_SCOPES: frozenset[str] = frozenset({
    SCOPE_READ_ANY,
    SCOPE_WRITE_ANY,
    SCOPE_DELETE_ANY,
    SCOPE_CLEAR_ALL,
    SCOPE_ADMIN_KEYS,
    SCOPE_EVOLVE,
})

# ---------------------------------------------------------------------------
# Role presets — convenience bundles of scopes the operator hands out
# instead of enumerating individual scope strings on every key issuance.
# A ``Role`` is just a ``frozenset[str]``; ``ApiKeyService.create_key`` is
# scope-list shaped, so callers spread a role with ``scopes=list(ROLE_X)``.
# ---------------------------------------------------------------------------

#: Read-only access across all namespaces. Writes still restricted to owner.
ROLE_READER: frozenset[str] = frozenset({SCOPE_READ_ANY})

#: Read across namespaces + write across namespaces. Cannot bulk-delete
#: or clear; cannot manage other principals' keys.
ROLE_EDITOR: frozenset[str] = frozenset({SCOPE_READ_ANY, SCOPE_WRITE_ANY})

#: Full operator: every scope. Reserved for the deployment admin.
ROLE_ADMIN: frozenset[str] = ALL_SCOPES


@dataclass
class AuthContext:
    """The authenticated principal."""

    key_id: str
    owner: str
    scopes: frozenset[str]

    @property
    def is_anonymous(self) -> bool:
        """True when this is the anonymous fallback context emitted
        in opt-in mode for unauthenticated requests."""
        return self.key_id == ""

    def has_scope(self, scope: str) -> bool:
        """True when ``scope`` is in the principal's scope set."""
        return scope in self.scopes

    def require_scope(self, scope: str) -> None:
        """Raise ``403 Forbidden`` when the principal lacks ``scope``.

        Routes call this to gate elevated operations after a base
        authentication check has succeeded. Anonymous contexts (no
        scopes) always 403 here — opt-in mode lets unauthenticated
        callers reach the dependency but doesn't let them pass scope
        gates.
        """
        if not self.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: '{scope}'",
            )


def _anonymous_context() -> AuthContext:
    """Build the opt-in-mode fallback for unauthenticated requests."""
    return AuthContext(
        key_id="",
        owner=settings.auth_anonymous_owner,
        scopes=frozenset(),
    )


def default_namespace_for(
    meta_namespace: str | None,
    auth: AuthContext,
) -> str | None:
    """Resolve the effective namespace for a write request.

    Semantics:

    * Anonymous caller (opt-in mode, no key) → pass through whatever
      ``meta_namespace`` is, including ``None``. The route owns the
      decision of how to behave in that case.
    * Authenticated caller with an explicit ``meta_namespace`` →
      respected verbatim. Caller is deliberately writing to a shared
      workspace; the service layer enforces scope checks.
    * Authenticated caller with ``meta_namespace is None`` → default
      to ``auth.owner``. This is the standard auto-scoping path that
      makes "I just want to save my own stuff" work without callers
      explicitly setting namespace on every POST.

    Pure function; safe to call before any DB I/O.
    """
    if auth.is_anonymous:
        return meta_namespace
    if meta_namespace is not None:
        return meta_namespace
    return auth.owner


def default_read_namespace_for(
    query_namespace: str | None,
    auth: AuthContext,
) -> str | None:
    """Resolve the namespace filter for a read (list) request.

    Closes the §3 P1 follow-up from iter #33: writes auto-scope to
    ``auth.owner``; reads should mirror that so a personal-key holder
    listing ``/v1/agents`` doesn't see every other namespace's data.

    Semantics:

    * Anonymous caller (opt-in mode, no key) → pass through whatever
      ``query_namespace`` is. The "anonymous can list everything in
      dev/CI" behaviour is intentional; production strict-mode
      deployments simply never reach this branch.
    * Authenticated caller with an explicit ``?namespace=X`` query →
      respected verbatim. Caller is deliberately querying a specific
      namespace. (Cross-namespace access without ``read:any`` may be
      enforced separately as a 403 at the service layer — out of
      scope here.)
    * Authenticated caller with no ``?namespace`` AND the
      ``read:any`` scope → return ``None`` so the caller sees every
      namespace. This is the explicit opt-in for cross-namespace
      reads.
    * Authenticated caller with no ``?namespace`` AND no ``read:any``
      → default to ``auth.owner``. Mirrors the writes-side
      auto-scoping so "I just want to see my own stuff" works
      without callers explicitly setting ``?namespace=alice`` on
      every list call.

    Pure function; safe to call before any DB I/O.
    """
    if auth.is_anonymous:
        return query_namespace
    if query_namespace is not None:
        return query_namespace
    if auth.has_scope(SCOPE_READ_ANY):
        return None
    return auth.owner


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """FastAPI dependency: validate ``Authorization: Bearer <jwt>`` or
    ``X-API-Key: <key>``.

    Two coexisting auth schemes:

    * **OIDC bearer** (`Authorization: Bearer ...`) — verified against
      the configured OIDC provider. Active when
      ``settings.oidc_enabled`` is True. When both schemes are
      supplied, Bearer wins.
    * **X-API-Key** — verified against the local ``api_keys`` table.
      The original auth path; preserved unchanged.

    Behaviour switches on ``settings.auth_required``:

    * **Strict** (True): missing both → 401, invalid → 401.
    * **Opt-in** (False, default): missing both → anonymous context;
      invalid (revoked / signature / claim mismatch) → 401. A leaked-
      then-revoked credential can't silently downgrade.
    """
    bearer_token = _extract_bearer_token(authorization)

    if bearer_token is not None:
        # Bearer presented — try OIDC verification first.
        from .oidc import OIDCError, get_oidc_verifier

        try:
            verifier = get_oidc_verifier()
        except OIDCError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"OIDC misconfigured: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        if verifier is None:
            # Bearer supplied but OIDC isn't enabled — surface that
            # explicitly so operators know the token will never work.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Bearer token received but OIDC is disabled "
                    "(set OIDC_ENABLED=true and configure OIDC_ISSUER)."
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            claims = verifier.verify(bearer_token)
        except OIDCError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return AuthContext(
            # Use the JWT's own identifier — the `jti` claim if
            # present, otherwise the `sub` so AuthContext.is_anonymous
            # (`key_id == ""`) reads correctly.
            key_id=str(claims.raw.get("jti") or claims.sub),
            owner=claims.sub,
            scopes=claims.scopes,
        )

    if not x_api_key:
        if settings.auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-API-Key or Authorization: Bearer header",
                headers={"WWW-Authenticate": "Bearer, X-API-Key"},
            )
        return _anonymous_context()

    svc = ApiKeyService(db)
    row = await svc.verify_key(x_api_key)
    if row is None:
        # Always 401 on invalid — even in opt-in mode — so a revoked
        # key never silently downgrades the caller to anonymous.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
    return AuthContext(
        key_id=str(row.key_id),
        owner=row.owner,
        scopes=frozenset(row.scopes or ()),
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Pull the token out of ``Authorization: Bearer <token>``.

    Returns ``None`` for missing / non-Bearer / empty headers. Case
    insensitive on the scheme name per RFC 6750.
    """
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
