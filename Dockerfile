# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install project metadata and dependencies
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[dev]"

# Copy test suite for verification target
COPY tests/ ./tests/

CMD ["pytest"]
