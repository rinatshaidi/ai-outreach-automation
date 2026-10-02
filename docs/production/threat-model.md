# Production threat model

Status: planning draft for Stage 11. It does not authorize deployment or real delivery.

## Assets

- owner credentials and active sessions;
- Candidate Profile and permission/consent history;
- researched company and public-contact records;
- draft and revision history;
- delivery approvals, messages and audit events;
- PostgreSQL data and backups;
- runtime secrets and future mailbox credentials;
- domain, DNS, hosting and monitoring accounts.

## Trust boundaries

1. Owner browser to protected HTTPS access layer.
2. Access layer/reverse proxy to FastAPI.
3. FastAPI to PostgreSQL.
4. FastAPI to public research sources.
5. Future FastAPI to AI/email providers, only after separate approval.
6. Production host to off-host backup and monitoring destinations.

## Threats and required controls

| Threat | Existing control | Required before production | Residual decision |
|---|---|---|---|
| Anonymous access to private data | Owner session middleware | Private gateway/VPN or protected HTTPS; verify every private route | Access model |
| Credential guessing | Argon2id, login rate limit and audit | Perimeter rate limit/alert; strong rotated password | 2FA/gateway choice |
| Session theft | Opaque hashed sessions, expiry, revocation | HTTPS, Secure cookies, protected owner device | Session duration |
| CSRF | Login CSRF and session CSRF validation | HTTPS acceptance test through proxy | None |
| Database exposure | Local Docker network | No host/public DB port; firewall verification | Hosting network |
| Secret disclosure | `.env` ignored; safe log fields | Approved secret store, least privilege and rotation runbook | Secret manager |
| Malicious researched page / SSRF | URL normalization, public-IP check, content allowlist | Egress monitoring and patch process | Allowed research policy |
| Prompt injection / untrusted AI output | Web/AI treated as untrusted; validators and owner gates | Provider data policy and purpose permission review | AI provider |
| Unauthorized real send | Fail-closed flags, approval, token, consent, idempotency | Keep disabled during deployment; separate real-send acceptance | Mail provider/legal |
| Accidental duplicate delivery | Idempotency and prior-send check | Provider-level reconciliation and one-recipient first test | First-send scope |
| Backup theft | Local backups only | Encryption before off-host copy; restricted keys | Backup destination |
| Data loss/corruption | PostgreSQL and migration backups | Automated backups plus isolated restore proof | RPO/RTO acceptance |
| Host compromise | Container non-root app | OS patching, firewall, private access, no-new-privileges | Hosting owner |
| Dependency/CDN compromise | Version constraints and CSP | Patch cadence; consider self-hosting browser assets | Private/public exposure |
| Audit tampering | Append-only application pattern | Restricted DB admin access and off-host backup/log retention | Log destination |
| Excess retention of contact data | Manual records and suppression | Written retention/deletion policy and periodic review | Jurisdiction |

## Production acceptance security checks

- [ ] `APP_ENVIRONMENT=production` and `DEMO_MODE=false`.
- [ ] `AUTH_REQUIRED=true` and `AUTH_COOKIE_SECURE=true`.
- [ ] `ALLOW_REAL_EMAIL=false`, publication OFF and export OFF.
- [ ] HTTPS certificate and redirect verified.
- [ ] Exact trusted proxy IP configured; wildcard proxy trust forbidden.
- [ ] Anonymous requests cannot access UI, APIs or PII.
- [ ] Login, logout, expiry, revocation, rate limit and CSRF tested through the proxy.
- [ ] PostgreSQL has no public/host port.
- [ ] Secrets absent from git, image history, Compose output, logs and screenshots.
- [ ] Backup encryption, off-host copy and isolated restore verified.
- [ ] Health, disk, DB, backup and application-error alerts tested.
- [ ] Public API docs either protected by the perimeter or disabled.
- [ ] Dependency and base-image patch process assigned.
- [ ] Incident disable path documented and tested.

## Immediate kill switches

If suspicious activity or configuration drift is detected:

1. block network access at the approved gateway/firewall;
2. keep or set `ALLOW_REAL_EMAIL=false`, publication OFF and export OFF;
3. revoke owner sessions by rotating credentials locally;
4. stop the application container without deleting PostgreSQL volumes;
5. preserve logs and create an encrypted database backup;
6. rotate affected secrets from the owning provider;
7. investigate before restoring access.

