FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY nawa ./nawa
# Demo data loader: passed as the named build context `seed` (see docker-compose.yml).
COPY --from=seed . ./seed
RUN uv sync --frozen --no-dev

RUN useradd --system --create-home nawa \
    && mkdir -p /data/uploads \
    && chown nawa /data/uploads
USER nawa
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/seed
EXPOSE 8000
CMD ["uvicorn", "nawa.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
