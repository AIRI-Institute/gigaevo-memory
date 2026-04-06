FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Install gigaevo_memory from local source with caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=client/python/pyproject.toml,target=/tmp/client/python/pyproject.toml \
    --mount=type=bind,source=client/python/README.md,target=/tmp/client/python/README.md \
    --mount=type=bind,source=client/python/src,target=/tmp/client/python/src \
    uv pip install --system /tmp/client/python

# Copy and install web_ui dependencies with caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=web_ui/pyproject.toml,target=pyproject.toml \
    uv pip install --system -e .

COPY web_ui/app/ ./app/

# Create examples directory and copy example chain files
RUN mkdir -p /app/examples
COPY client/python/examples/chain_v0.json /app/examples/
COPY client/python/examples/chain_v1.json /app/examples/

ENV GRADIO_SERVER_NAME=0.0.0.0
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]
