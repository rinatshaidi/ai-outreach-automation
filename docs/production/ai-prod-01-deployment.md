# ai-prod-01 private deployment record

Deployment date: 2026-08-11 (Europe/Moscow).

## Target and boundaries

- Approved host: `ai-prod-01` (`165.232.68.212`, DigitalOcean FRA1).
- Protected VPN host `revpn-01` (`165.22.95.1`) was not accessed or changed.
- Release: `20260811_130404`.
- Release directory: `/opt/ai-outreach-system/releases/20260811_130404`.
- Current symlink: `/opt/ai-outreach-system/current`.
- Secret file: `/etc/ai-outreach-system/production.env`, mode `0600`.
- The working local database and personal/contact data were not uploaded.

## Isolation

- Compose project: `ai-outreach-production`.
- Application container: `ai-outreach-production-app-1`.
- Background container: `ai-outreach-production-worker-1`.
- Database container: `ai-outreach-production-postgres-1`.
- Network: `ai-outreach-production_default`.
- Volume: `ai-outreach-production_postgres_data`.
- Host binding: `127.0.0.1:8010`; no public application port.
- Public HTTPS entrypoint: `https://outreach.shaidigroup.com` through the dedicated Nginx
  virtual host.
- The host PostgreSQL service and JobMonitor containers are not used by AI Outreach.

## Verified state

- Application: healthy.
- PostgreSQL: healthy.
- Alembic: `20260810_0019 (head)`.
- Readiness endpoint: `status=ok`, `database=ok`.
- Login page: HTTP 200 from the server loopback interface.
- External HTTP redirects to HTTPS.
- External HTTPS readiness endpoint: `status=ok`, `database=ok`.
- Let's Encrypt certificate: issued for `outreach.shaidigroup.com`, expires 2026-11-09 and is
  managed by the existing Certbot renewal timer.
- Runtime: production.
- Authentication: required.
- Secure cookies: enabled.
- Real email: disabled.
- Publication: disabled.
- External export: disabled.
- SMTP test mode: disabled.
- Search Task execution: dedicated PostgreSQL-backed worker, 5-second polling, restart policy
  `unless-stopped`, heartbeat healthcheck and bounded interruption recovery.
- OpenAI: key not configured; provider unavailable; external AI data gate disabled.
- Server swap: 2 GiB, persisted in `/etc/fstab`.

## Initial database backup

- File: `/opt/ai-outreach-system/backups/initial_0019_20260811.dump`.
- Format: PostgreSQL custom dump.
- Size at creation: 149,131 bytes.
- Mode: `0600`.
- `pg_restore -l` validation: passed.
- SHA-256: `6ba916764c9d2115273861c573d675557e6dcef8b550ba9674f7c8aa4a718f8a`.

This is a local-on-host bootstrap backup, not the still-required encrypted off-host backup policy.

## Working database import

Completed on 2026-08-11 after explicit owner approval.

- Fresh local source dump:
  `backups/pre_production_transfer_20260811_145521.dump`.
- Source dump SHA-256:
  `cbc51cd5d9cfae456ec21003d86816f0f359e9c478fd30dd44dd13e12f703d42`.
- Production rollback dump:
  `/opt/ai-outreach-system/backups/pre_local_import_20260811_145521.dump`.
- The source dump was restored into a temporary server database and validated before the live
  database was changed.
- The existing production owner password hash was preserved and verified after restore.
- Existing sessions were revoked; the owner must log in again.
- Final Alembic revision: `20260810_0019`.
- Verified counts: 1 profile, 3 experiences, 4 skills, 8 strengths, 6 facts, 3 contacts,
  9 companies, 21 opportunities, 1 search task and 39 message drafts.
- External HTTPS readiness and login page checks passed.

## Remaining acceptance items

1. Owner signs in over HTTPS so authenticated UI smoke can be completed without sharing a
   password.
2. Owner explicitly approves the exact Candidate Profile fields that may be sent to OpenAI for
   draft rewriting, then configures the key interactively on the VPS.
3. Select an encrypted off-host backup destination and monitoring destination.

## Stage 11 worker release

- Release: `20260811_152750`.
- Release archive SHA-256:
  `7011820b6f4a609abd2c01cc0c1099528163520871a1cd305bf09ce55751de75`.
- Pre-release database backup:
  `/opt/ai-outreach-system/backups/pre_worker_20260811_152750_0019.dump`.
- The backup is non-empty and its PostgreSQL custom archive listing was validated before the
  release symlink changed.
- No migration was added or applied by this release; Alembic remains `20260810_0019`.
