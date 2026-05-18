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

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
