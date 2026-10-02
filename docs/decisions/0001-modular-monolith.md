# ADR 0001: Modular monolith for MVP

- Status: accepted
- Date: 2026-07-31

## Decision

Use one FastAPI application with module boundaries and provider adapters. Do not add Redis,
Celery, React or microservices during the baseline.

## Rationale

This is the smallest architecture that satisfies the v1.2 specification, remains observable
and testable, and leaves domain logic separable for later extraction.

