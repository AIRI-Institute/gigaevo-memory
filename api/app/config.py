"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_dsn: str = "postgresql+asyncpg://memory:memory_dev_password@postgres:5432/memory"
    redis_url: str = "redis://redis:6379/0"
    api_secret_key: str = "dev-secret-key-change-in-production"
    enable_vector_search: bool = False
    vector_dimension: int = 384

    # Embedding service configuration
    embedding_provider: str = "sentencetransformers"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    sentencetransformers_device: str | None = None  # cpu|cuda|mps
    openai_api_key: str | None = None
    huggingface_api_key: str | None = None

    # Hybrid search configuration
    hybrid_default_bm25_weight: float = 0.5
    hybrid_default_vector_weight: float = 0.5

    # Authentication (P1 §3). When ``auth_required=False`` (default),
    # missing ``X-API-Key`` headers don't 401 — the route sees an
    # anonymous ``AuthContext`` (owner="anonymous", empty scopes).
    # When the header IS supplied, it must still validate. This dual
    # mode lets the project ship `Depends(require_api_key)` on every
    # router without breaking dev / test setups.
    # Production deployments flip it on via ``AUTH_REQUIRED=true``.
    auth_required: bool = False
    auth_anonymous_owner: str = "anonymous"

    # Reranker (P2 §4). Optional second-pass reordering of search
    # hits after BM25 / vector / hybrid retrieval. `"identity"` is the
    # default no-op; alternative implementations (cross-encoder,
    # custom external service) register themselves via
    # ``RerankerRegistry``.
    reranker_kind: str = "identity"

    # OIDC integration (P3 §3). When enabled, the auth dependency
    # accepts ``Authorization: Bearer <jwt>`` in addition to
    # ``X-API-Key``. Verification: signature against the issuer's
    # JWKS, then `iss` / `aud` / `exp` checks. The `sub` claim maps
    # to ``AuthContext.owner``; the configured scopes claim maps to
    # ``AuthContext.scopes``. Coexists with X-API-Key — when a
    # request supplies both, the Bearer token wins (it's stronger).
    oidc_enabled: bool = False
    oidc_issuer: str | None = None
    oidc_jwks_uri: str | None = None
    oidc_audience: str | None = None
    oidc_sub_claim: str = "sub"
    oidc_scopes_claim: str = "scope"
    oidc_jwks_cache_ttl_seconds: int = 600
    # Clock skew tolerance for `exp` / `iat` / `nbf` checks (seconds).
    oidc_leeway_seconds: int = 30

    # SSE backpressure (P2 §6). Lag is measured as the wall-clock gap
    # between the event's publisher-side timestamp and the moment the
    # forwarder is ready to yield it. A laggy subscriber gets a
    # `lag_warning` event injected (still receives the original event
    # after); a chronically-slow subscriber is dropped to free server
    # resources. Both thresholds are configurable via env.
    sse_warn_lag_seconds: float = 10.0
    sse_drop_lag_seconds: float = 60.0

    # CORS (CARE PREPARE §1.9). Comma-separated list of allowed
    # origins for browser clients. ``"*"`` (the default) is permissive
    # for local dev but the FastAPI / Starlette stack will silently
    # disable credentialed CORS when the list is a wildcard; explicit
    # origins are required for cookie-bearing or ``X-API-Key`` flows
    # from a browser. Production deployments should set
    # ``CORS_ALLOWED_ORIGINS=https://care.example,https://app.example``.
    cors_allowed_origins: str = "*"
    cors_allow_credentials: bool = True
    cors_allowed_methods: str = "*"
    cors_allowed_headers: str = "*"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """Parse ``cors_allowed_origins`` into a list of stripped tokens."""
        raw = self.cors_allowed_origins.strip()
        if not raw:
            return []
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def cors_allowed_methods_list(self) -> list[str]:
        raw = self.cors_allowed_methods.strip()
        if not raw:
            return []
        return [m.strip() for m in raw.split(",") if m.strip()]

    @property
    def cors_allowed_headers_list(self) -> list[str]:
        raw = self.cors_allowed_headers.strip()
        if not raw:
            return []
        return [h.strip() for h in raw.split(",") if h.strip()]

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
