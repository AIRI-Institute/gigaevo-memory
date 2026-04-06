FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Copy dependency definitions
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install dependencies with caching using uv sync
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked

FROM base AS test

# Install dev dependencies and run tests
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

COPY tests/ ./tests/
COPY pyproject.toml ./

CMD ["uv", "run", "pytest", "tests/", "-v"]

FROM base AS runtime

# Copy installed package from base
COPY --from=base /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code
COPY src/ ./src/

CMD ["python", "-c", "import gigaevo_memory; print(f'gigaevo-memory v{gigaevo_memory.__version__}')"]
