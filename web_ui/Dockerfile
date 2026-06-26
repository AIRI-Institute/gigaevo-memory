FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Copy app source first so the editable install can resolve the `app` package
# (hatchling needs the package dir present to build the editable wheel).
COPY web_ui/app/ ./app/

# Install web_ui and its dependencies into system Python. gigaevo-client is
# pulled from PyPI via the web_ui pyproject — the SDK source no longer lives in
# this repo (it was extracted to its own repository).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=web_ui/pyproject.toml,target=pyproject.toml \
    uv pip install --system -e .

# The example chain files used to live under client/python/examples (now part of
# the extracted SDK repo). The showcase tab degrades gracefully when they are
# absent; create the directory so its load path resolves cleanly.
RUN mkdir -p /app/examples

ENV GRADIO_SERVER_NAME=0.0.0.0
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]
