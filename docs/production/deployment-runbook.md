# Private production deployment runbook

Status: design only. Every step that changes a server, DNS, account or external service requires
separate owner authorization.

## Preconditions

- Stage 10 accepted and Stage 11 decisions D1–D6 recorded.
- Target host/access method, jurisdiction and owner selected.
- Backup destination, monitoring destination and secret storage selected.
- No real email, publication or export authorized.
- A fresh local regression and migration-head check passes.

## Planned deployment boundary

- Use `compose.production.example.yaml` as a reviewed template, not as an automatic deployment.
- App binds only to `127.0.0.1`; the approved private HTTPS proxy/access layer is the only entry.
- PostgreSQL publishes no host port.
- Production environment values come from the approved secret store.
- The first deployment has no Mailpit and no production mailbox; all delivery modes are disabled.

## Pre-deployment evidence

Record without secret values:

- application revision/commit or immutable source package identifier;
- Alembic current/head;
- image digest;
- backup file identifier, size, timestamp and verification result;
- target hostname and access policy;
- expected firewall listeners;
- rollback package/image identifier;
- owner approval reference.

## Planned sequence

1. Create and verify a local pre-deployment backup.
2. Build immutable images from the reviewed source.
3. Scan configuration output for unexpected ports, flags and secret exposure.
4. Provision the target private network/access layer.
5. Install runtime and OS security updates.
6. Configure firewall: protected HTTPS/access port only; no PostgreSQL public port.
7. Inject secrets through the approved store.
8. Start PostgreSQL and verify health.
9. Apply Alembic migrations once.
10. Start FastAPI behind the approved proxy.
11. Verify HTTPS, Secure cookies and trusted proxy handling.
12. Create/rotate the single owner locally on the target without command-line passwords.
13. Run security and functional acceptance with external actions disabled.
14. Configure and test encrypted backups and monitoring.
15. Record outcome and either accept the deployment or execute rollback.

## Acceptance

- [ ] Only approved listeners are exposed.
- [ ] Anonymous private-route access is denied.
- [ ] Login and CSRF work over HTTPS.
- [ ] Candidate Profile and company data are intact.
- [ ] Dashboard/Companies/Letters/Profile/Settings smoke passes.
- [ ] `alembic current` equals `alembic heads`.
- [ ] Real send, publication and export return fail-closed results.
- [ ] Backup restore proof is current.
- [ ] Monitoring alerts reach the owner.
- [ ] No secret or PII appears in logs/config output.

## Rollback

Rollback never deletes a volume or overwrites the only database copy.

1. Block external/private gateway access.
2. Stop the application container only.
3. Preserve logs and create a new encrypted incident backup.
4. If schema/data rollback is required, restore the last verified backup into a separate database.
5. Validate the separate restore before changing service routing.
6. Restart the previous reviewed application image against a compatible database only after review.
7. Document the reason, evidence and owner approval.

## Explicitly excluded

- real email or mailbox integration;
- DNS/domain purchase without approval;
- public registration or multi-user work;
- automated deployment from an unreviewed branch;
- destructive database reset;
- copying local secrets or `.env` to the server;
- uploading local data before jurisdiction/retention approval.

