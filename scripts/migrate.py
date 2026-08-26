#!/usr/bin/env python3
"""Apply versioned SQL migrations to the configured PostgreSQL database.

Usage:
    DATABASE_URL='postgresql://...' python scripts/migrate.py

The runner never provisions a database, logs credentials, or changes application
safety configuration.  Railway's private PostgreSQL ``DATABASE_URL`` is expected
only after the user separately provisions the service and links the variable.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
ADVISORY_LOCK_KEY = 8_453_001


def migration_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def apply_migrations(database_url: str) -> list[str]:
    """Apply each unapplied migration once and return applied version names."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            try:
                for path in migration_files():
                    version = path.name
                    checksum = migration_checksum(path)
                    cursor.execute("SELECT to_regclass('public.autotrader_schema_migrations')")
                    table_exists = cursor.fetchone()[0] is not None
                    if table_exists:
                        cursor.execute(
                            "SELECT checksum FROM autotrader_schema_migrations WHERE version = %s",
                            (version,),
                        )
                        existing = cursor.fetchone()
                        if existing:
                            if existing[0] != checksum:
                                raise RuntimeError(
                                    f"Migration checksum changed after application: {version}."
                                )
                            continue

                    # SQL files own their explicit BEGIN/COMMIT boundaries, so the
                    # connection is deliberately autocommit-enabled.
                    cursor.execute(path.read_text(encoding="utf-8"))
                    cursor.execute(
                        "INSERT INTO autotrader_schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, checksum),
                    )
                    applied.append(version)
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    return applied


def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required; no migration was attempted.", file=sys.stderr)
        return 2
    try:
        applied = apply_migrations(database_url)
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    else:
        print("Database schema is already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
