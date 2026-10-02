# Candidate Profile and permissions

## Data boundary

The profile is single-owner in MVP. Structured facts and contacts hold explicit permissions;
free-form profile text is never implicitly converted into an externally usable fact.

## Permission chain

1. `store_private` must be enabled before any use permission.
2. `use_for_ai_analysis` permits inclusion only in an AI-purpose fact pack.
3. `use_in_draft` permits draft generation.
4. `send_externally` additionally requires `use_in_draft`.
5. `publish_publicly` is independent from sending and remains disabled by default.

Contacts included in a signature must also be verified and have `allowed_in_signature=true`.

## Auditability

Permission changes append `ConsentEvent` records with entity, scope, decision, timestamp and
request ID. Events are not updated or deleted through the Stage 1 API.

## Concurrency

Profile, fact and contact mutations compare a supplied version with the current version. A
stale request returns HTTP 409 and does not overwrite newer data.

