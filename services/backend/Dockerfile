FROM ghcr.io/astral-sh/uv:0.9.4-python3.14-bookworm-slim

WORKDIR /app
ARG BACKEND_DEPENDENCY_GROUPS=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY src ./src
RUN if [ -n "$BACKEND_DEPENDENCY_GROUPS" ]; then \
      uv sync --frozen --no-dev --group "$BACKEND_DEPENDENCY_GROUPS"; \
    else \
      uv sync --frozen --no-dev; \
    fi

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["uvicorn", "tripweave.entrypoints.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
