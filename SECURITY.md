# Security policy

## Baseline guarantees

- Real email, publication and external export are disabled by default.
- Secrets and personal data must not be committed, logged or included in demo artifacts.
- `.env.example` contains synthetic development values only.
- Web content and AI output are treated as untrusted input.
- Sensitive external actions require server-side authorization, consent and audit checks.
- Real delivery additionally requires a non-demo runtime, an explicit feature flag, a bearer
  owner secret, a current one-time draft approval and an idempotency key.
- Delivery logs and API responses expose only a masked recipient and safe error codes; message
  bodies and SMTP credentials must never be logged.
- Follow-up proposals are never sent automatically. Manual outcomes cancel open follow-ups,
  and suppression or an inactive campaign cancels them before further action.
- Analytics is read-only, uses parameterized ORM queries and returns only records already
  available to the local owner. Screenshots and demo fixtures contain reserved synthetic
  `.example` identities only.
- Private routes require the single-owner session when `AUTH_REQUIRED=true`. Passwords use
  Argon2id, only session-token hashes are stored, login attempts are rate-limited and audited,
  and POST/PUT/PATCH/DELETE requests require a matching CSRF cookie/header or form token.
- There is no public registration or password-reset endpoint. Owner credentials are created or
  rotated only with the local interactive script, which revokes existing sessions on rotation.
- Profile import is preview-first and fail-closed: requested verification and permissions are
  discarded, conflicts cannot be applied implicitly, and every imported record stays unverified.

## Reporting

Do not create a public issue containing credentials, personal data or message content.
Report security-sensitive findings privately to the repository owner.

## Supported status

Stage 10 local validation is complete. Stage 11 is a production decision, not an authorization
to deploy or send. Guarded real SMTP exists in the baseline, but production data, public access,
publication, export and external delivery remain prohibited until the corresponding decisions in
`STAGE_11_PRODUCTION_DECISION.md` are explicitly accepted.
