# Stage 0 baseline

The MVP starts as a modular monolith with one FastAPI process and one PostgreSQL database.
Server-rendered Jinja2 pages use HTMX for partial updates and Bootstrap for layout.

## Runtime boundaries

- FastAPI owns business rules, HTTP routes and server-rendered UI.
- PostgreSQL is the only source of truth.
- SQLAlchemy models are separate from API DTOs.
- Alembic is the only supported way to evolve the schema.
- Mailpit is the only email destination in development and demo modes.
- Redis, Celery, React and production SMTP are intentionally deferred.

## Fail-closed defaults

`DEMO_MODE=true`, `ALLOW_REAL_EMAIL=false`, `ALLOW_PUBLICATION=false` and
`ALLOW_EXTERNAL_EXPORT=false`. Enabling real delivery while demo mode is active prevents
application startup.

