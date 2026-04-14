#!/usr/bin/env python3
"""
Wait for PostgreSQL to be ready, then run Alembic migrations.

Used as Railway preDeployCommand so migrations don't fire before
the DB plugin is accepting connections.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys


def _normalize_url(url: str) -> str:
    """Strip asyncpg/psycopg2 driver prefix so asyncpg.connect() accepts it."""
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")
    return url


async def wait_for_db(
    url: str,
    max_retries: int = 30,
    retry_interval: float = 2.0,
) -> None:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg not installed – skipping DB readiness check", file=sys.stderr)
        return

    pg_url = _normalize_url(url)
    print(f"Waiting for database (up to {max_retries * retry_interval:.0f}s)...")

    for attempt in range(1, max_retries + 1):
        try:
            conn = await asyncpg.connect(pg_url, timeout=5)
            await conn.close()
            print(f"Database is ready (attempt {attempt})")
            return
        except Exception as exc:
            print(
                f"  [{attempt}/{max_retries}] not ready yet: {exc}",
                file=sys.stderr,
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_interval)

    print("Database did not become ready in time — aborting.", file=sys.stderr)
    sys.exit(1)


def run_migrations() -> None:
    print("Running: alembic upgrade head")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        check=False,
    )
    if result.returncode != 0:
        print("Alembic migration failed.", file=sys.stderr)
        sys.exit(result.returncode)
    print("Migrations complete.")


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL is not set — cannot run migrations.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(wait_for_db(db_url))
    run_migrations()
