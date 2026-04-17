FROM python:3.11-slim

WORKDIR /app

# System deps: libpq for asyncpg, gcc for tgcrypto (C ext), libjpeg/zlib for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 1: install Python dependencies (cached until pyproject.toml changes) ──
COPY pyproject.toml .
# Create minimal package stubs so hatchling can resolve the project without full source.
# Real source is copied afterwards; PYTHONPATH=/app takes priority over site-packages.
RUN mkdir -p bot worker db services scripts && \
    for d in bot worker db services; do touch $d/__init__.py; done
RUN pip install --no-cache-dir .

# ── Layer 2: copy source (invalidates only when code changes, not deps) ──
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
