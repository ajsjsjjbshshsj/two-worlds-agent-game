# Stage 1: Build virtual environment with locked dependencies
FROM python:3.12-slim-bookworm AS builder

# Install pinned uv tool
RUN pip install --no-cache-dir uv==0.13.6

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Install locked dependencies first for optimal Docker layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Copy package source and build/install the twoworlds package as non-editable wheel
COPY src ./src
COPY README.md ./README.md
COPY hatch_build.py ./hatch_build.py
RUN uv sync --locked --no-dev --no-editable

# Stage 2: Minimal runtime image
FROM python:3.12-slim-bookworm AS runner
WORKDIR /app

# Security: Create non-root user and group
RUN groupadd -g 10001 twoworlds && \
    useradd -u 10001 -g twoworlds -s /bin/sh -m twoworlds

# Copy virtual environment from builder stage
COPY --from=builder --chown=twoworlds:twoworlds /app/.venv /app/.venv

# Create persistent data directory owned by non-root user
RUN mkdir -p /data && chown -R twoworlds:twoworlds /data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER twoworlds:twoworlds

EXPOSE 8000

CMD ["python", "-m", "twoworlds.server"]
