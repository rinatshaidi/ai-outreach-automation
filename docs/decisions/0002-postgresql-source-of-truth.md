# ADR 0002: PostgreSQL is the source of truth

- Status: accepted
- Date: 2026-07-31

## Decision

Use PostgreSQL for persistent state, SQLAlchemy for mapping and Alembic for every schema change.
Google Sheets and local files are not authoritative stores.

