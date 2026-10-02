# Stage 11 — Production Decision

## Current status

**PRODUCTION DEPLOYED / ACCEPTANCE IN PROGRESS**

**PRIVATE_INFRASTRUCTURE_DEPLOYMENT_GO = YES (owner approved 2026-08-11)**  
**PUBLIC_ACCESS_GO = NO (domain/TLS pending)**  
**REAL_SEND_GO = NO**

Production is deployed as an isolated Compose project on the approved `ai-prod-01` host.
Application, PostgreSQL and the dedicated background worker are healthy. The working database
was migrated with the owner password hash preserved. Real email, publication and external
export remain disabled.

## Current Stage 11 execution model

- Search Tasks are durably queued in PostgreSQL and executed by a separate `worker` service.
- Browser requests only create/start tasks; they do not own the execution lifecycle.
- The worker polls every 5 seconds, atomically claims tasks and writes stage audit events.
- Interrupted RUNNING tasks are requeued on worker startup; repeated interruptions end in a
  human-readable FAILED state after the configured retry ceiling.
- Research, deeper research and Contact Discovery still execute synchronously when manually
  requested. Moving them into the same durable job model is a later hardening step, not a reason
  to add Redis/Celery to the single-owner pilot.
- Follow-ups are proposals only and are never auto-sent.

## Production AI provider decision

- Provider: OpenAI API, server-side only.
- When configured, `OPENAI_API_KEY` exists only in
  `/etc/ai-outreach-system/production.env` (mode `0600`).
- The key is intentionally absent from `.env.example`, production examples, UI and logs.
- Requests use the Responses API with `store=false`.
- Candidate facts are eligible only when their record explicitly allows AI analysis.
- A second fail-closed gate (`ALLOW_OWNER_DATA_TO_AI`) prevents provider activation until the
  owner explicitly approves the exact data category, destination and purpose.
- Current production state: `OPENAI_API_KEY=configured`; a secret-safe production call returned
  `provider=working` on 2026-08-11.

## Gmail production mailbox decision (implementation prepared locally)

- Use the owner's Gmail through Google OAuth 2.0 and Gmail API; never use the Gmail password.
- Use minimum scopes for the approved send/sync functions.
- Store OAuth client secret and refresh token only as protected production secrets.
- Preserve Gmail thread/message IDs for outbound and inbound mapping.
- For this single-user MVP, prefer a safe periodic Gmail API sync in the existing background
  service. Gmail watch + Pub/Sub is deferred unless polling proves insufficient.
- Stop at the Google Cloud Console/OAuth consent step and give the owner exact click-by-click
  values. OAuth secrets must never be pasted into chat.
- OAuth, encrypted refresh-token persistence, Gmail API delivery, thread/message mapping,
  thread-scoped reply sync, follow-up cancellation and owner-facing status controls are
  implemented locally at migration `20260811_0020`.
- Local regression: 145 tests passed; Ruff and strict mypy passed.
- Google Cloud client creation, production deployment/configuration, OAuth consent, Gmail sync,
  and all real sending remain OFF pending the owner's console action.

Stage 10 is complete and the application is ready for a production decision, but that does not
make the current local Docker environment production-ready. This document separates decisions
from implementation and keeps every external action blocked until the owner explicitly approves
its scope.

Audit date: 2026-08-11 (Europe/Moscow).

## What is already proven

- Stage 10 completion status: `DONE`.
- Candidate Profile computed status: `READY_FOR_LOCAL_PILOT`.
- Alembic head: `20260810_0019`.
- Local Docker application, PostgreSQL and Mailpit are healthy.
- Full regression gate: 134 tests passed; Ruff and strict mypy passed.
- Single-owner authentication, Argon2id passwords, session revocation, CSRF protection, login
  rate limiting and audit history work locally.
- Real delivery is fail-closed and requires a non-demo runtime, an owner bearer secret, an exact
  current approval, an idempotency key, a verified non-suppressed recipient and current external
  consent.
- Test and real delivery modes are separated.
- Auto-send does not exist. Follow-up proposals are owner-reviewed and are never auto-sent.
- Publication and external export are disabled.
- Local pre-migration backups exist through revision `0018 -> 0019`.

## Readiness audit

| Area | Current state | Production decision |
|---|---|---|
| Application workflow | Proven in Local Pilot | Ready for controlled deployment planning |
| Database schema | Alembic `0019` | Ready, but production migration/rollback runbook is absent |
| CI migration gate | Fixed to compare `alembic current` with actual `alembic heads` | Ready after local verification |
| Authentication | Single owner, password/session/CSRF/rate limit | Private perimeter or 2FA decision required |
| HTTPS and cookies | Local HTTP; `AUTH_COOKIE_SECURE=false` | HTTPS and `AUTH_COOKIE_SECURE=true` required |
| Reverse proxy | Not configured | Required before any network deployment |
| Domain/DNS | Not selected | Owner decision required if a public hostname is used |
| Network access | Localhost only | VPN/private access, IP allowlist or protected public access decision required |
| Secrets | Local `.env`, ignored by git | Production secret storage and rotation procedure required |
| Database backups | Manual local snapshots/dumps | Automated encrypted backups, retention and restore test required |
| Monitoring | Health endpoints and structured logs | Uptime, disk, DB, backup and error alerting required |
| Email | Mailpit only; guarded SMTP code exists | Mailbox/provider/legal approval required; remains OFF initially |
| Inbound replies | Manual outcomes only | Mailbox integration decision deferred or required before automation |
| Retention/deletion | Not formally defined | Policy required before real personal/contact data processing |
| Legal/jurisdiction | Not reviewed | Hosting and outreach jurisdictions must be selected and reviewed |
| Production Compose/runtime | Not present | Must be designed after hosting/access decisions |
| Real send | Technically blocked | Separate final authorization required after deployment acceptance |

## Blocking findings

These are blockers for an external production launch, not defects in the completed Local MVP.

1. Hosting and protected access method are not selected.
2. HTTPS, reverse proxy and secure-cookie production runtime are not configured.
3. Production secrets and a rotation/recovery procedure are not selected.
4. Automated encrypted PostgreSQL backup, off-host retention and restore proof are absent.
5. Monitoring and owner alert delivery are not configured.
6. Legal basis, contact-data retention and target jurisdictions are not approved.
7. Production mailbox/provider and sending-domain policy are not selected.
8. Real external sending has not been authorized and must remain disabled.

## Non-blocking technical observations

- API documentation routes are public in the current middleware allowlist. For a private owner
  deployment this can remain behind the network perimeter; for public exposure they should be
  disabled or separately protected.
- The UI loads Bootstrap and HTMX from public CDNs. A stricter production build may self-host and
  pin these assets, but private-pilot deployment does not require a UI redesign.
- The current backup script creates a gzip JSON snapshot and migration backups include `pg_dump`
  files. Neither constitutes a production backup policy until encryption, scheduling, off-host
  retention and restore testing are defined.
- Application health endpoints exist, but there is no alerting consumer.
- Two-factor authentication is not implemented in the application. A private network/access
  gateway can provide the second perimeter without expanding the app to multi-user SaaS.

## Recommended first production shape

The safest minimal next target is a **private single-owner production pilot**, not a publicly
accessible outreach service.

```text
Owner browser
  -> private access gateway / VPN
  -> HTTPS reverse proxy
  -> one FastAPI container
  -> one PostgreSQL service
  -> encrypted scheduled backup copied off-host

Real email, publication and export remain OFF.
```

Recommended principles:

- one owner only;
- no public registration;
- no public database port;
- application reachable only through HTTPS and the selected protected access layer;
- PostgreSQL reachable only on the private container/network boundary;
- secrets injected at runtime and never stored in git or images;
- daily encrypted database backup, off-host copy, and periodic restore test;
- health/error/backup/disk alerts sent to an owner-controlled channel;
- initial deployment uses Mailpit or no email adapter;
- production mailbox is connected only after infrastructure acceptance;
- the first real send, if later approved, is one explicitly selected draft to one explicitly
  selected recipient, with real-send flags enabled only for that controlled test window.

## Recommended operational targets

These defaults follow the v1.4 specification and can be changed by the owner:

- RPO: 24 hours.
- RTO: 4 hours.
- Database backups: daily, encrypted, off-host.
- Suggested initial retention: 7 daily + 4 weekly copies; final retention depends on legal review.
- Restore test: before launch, then at least monthly during the pilot.
- Deployment mode: manual, versioned, rollback-capable.
- Discovery schedule: manual during the private production pilot.
- Real email: OFF during infrastructure acceptance.
- Auto-send: permanently OFF for this MVP.

## Delivery decision

Production deployment and production email are two separate decisions.

### Deployment acceptance

A deployment may be accepted only after:

- backup and restore are proven;
- HTTPS and secure cookies are verified;
- anonymous/private-route access tests pass;
- secrets are not present in image, repository, logs or screenshots;
- database is not publicly exposed;
- monitoring alerts are tested;
- migrations, smoke tests and regression tests pass in the target environment;
- real email, publication and export remain OFF.

### Real-send acceptance

Real sending may be discussed only after deployment acceptance and requires another explicit
owner instruction covering:

- mailbox/provider and From identity;
- target jurisdictions and lawful basis;
- retention/suppression policy;
- exact sending limits and schedule;
- recipient eligibility rules;
- reply handling;
- one controlled first recipient/draft;
- rollback/disable procedure.

## Owner decisions required

Only the following decisions are needed before implementation planning. Secrets, passwords and
API keys must not be entered into this document or chat.

### D1 — Deployment intent

- Recommended: private single-owner production pilot.
- Alternative: remain local and defer Stage 11 implementation.

Owner choice: **APPROVED — private single-owner production pilot**

### D2 — Hosting and protected access

Specify whether an existing server or a new hosting account should be considered, and choose one
access model:

- Recommended: private VPN/access gateway plus application login.
- Alternative: public HTTPS with IP allowlist/access gateway and stronger perimeter controls.

Owner choice: **APPROVED — existing DigitalOcean server `165.232.68.212`, FRA1.**  
Initial application binding remains loopback-only. Public access is prohibited until HTTPS is
configured for a dedicated hostname.

Hard infrastructure boundary: `165.22.95.1` (`revpn-01`) is a VPN-only protected server and must
never be accessed or changed by this project. All deployments go only to `165.232.68.212`
(`ai-prod-01`) as separate Docker Compose projects with separate containers, networks and volumes.

### D3 — Domain and TLS

- Choose an existing domain/subdomain or approve a private hostname supplied by the access layer.
- HTTPS is mandatory in either case; plain HTTP production is rejected by policy.

Owner choice: **PENDING — dedicated outreach hostname is still required.**

### D4 — Data jurisdiction and retention

Choose:

- hosting country/region;
- initial target outreach countries;
- whether only company-level and official business/recruitment contacts are allowed initially;
- retention period for rejected companies, contacts, drafts and delivery history.

Owner choice: **PARTIAL — hosting region FRA1 (Germany) selected. No working database or real
contact data may be uploaded until retention and target-jurisdiction choices are accepted.**

### D5 — Production email strategy

- Recommended for the first deployment: no production mailbox; real email remains OFF.
- Later choose a dedicated sending mailbox using guarded SMTP or provider OAuth.

Owner choice: **APPROVED FOR INITIAL DEPLOYMENT — no production mailbox; real email remains OFF.**

### D6 — Backup and monitoring destination

Choose owner-controlled destinations for encrypted off-host backups and operational alerts.

Owner choice: **PENDING**

## Work allowed before these decisions

The following local, reversible work is allowed without external side effects:

- maintain this decision document;
- keep CI/tests/migration checks current;
- design, but not apply, production configuration templates;
- write backup/restore and deployment runbooks using placeholders;
- add tests for production fail-closed configuration;
- document threat model and retention choices as pending.

## Local planning artifacts completed

The following reversible, no-deployment artifacts are now available:

- `compose.production.example.yaml` — fail-closed private deployment template;
- `config/production.env.example` — placeholder-only configuration inventory;
- `docs/production/threat-model.md` — assets, boundaries, threats, controls and kill switches;
- `docs/production/deployment-runbook.md` — approval-gated deployment and rollback plan;
- `docs/production/backup-restore-runbook.md` — encrypted backup and isolated restore plan.

Dry validation confirms:

- application binds only to `127.0.0.1` for an approved proxy/access layer;
- PostgreSQL publishes no host port;
- production mode, authentication and Secure cookies are required;
- real email, publication, export and SMTP test mode remain disabled;
- no production service was started and no external system was changed.

The following remains prohibited until the corresponding owner decision:

- VPS/server mutation;
- account creation or paid service purchase;
- DNS/domain/TLS changes;
- production deployment;
- uploading the working database;
- creating production secrets or mailbox credentials;
- enabling `ALLOW_REAL_EMAIL`, publication or export;
- external email or message delivery;
- git push or publication.

## Next controlled step

1. Owner answers D1–D6 at the policy level without sharing secrets.
2. Create a target-specific architecture and implementation checklist.
3. Prepare local production templates and runbooks with placeholders.
4. Review the planned mutations and costs.
5. Request separate authorization before any infrastructure change.
6. Deploy with real email/publication/export still OFF.
7. Run production acceptance.
8. Request a separate decision for any real send.

Until D1–D6 are accepted, Stage 11 remains **DECISION_REQUIRED** and external production remains
**NO-GO**.
