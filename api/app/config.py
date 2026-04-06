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

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
