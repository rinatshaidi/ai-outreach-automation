# Guarded delivery

## Boundary

Stage 7 separates `test` and `real` email delivery while using one provider-neutral adapter.
Test delivery is accepted only when SMTP test mode is enabled and the host is local Mailpit
(`mailpit`, `localhost` or a loopback address). Its recipient is the configured synthetic
test inbox, never the company contact.

Real delivery is fail-closed. It requires all of the following in the same database
transaction:

- `ALLOW_REAL_EMAIL=true`, `DEMO_MODE=false` and a valid owner bearer token;
- the exact latest, unchanged and unconsumed draft approval plus its one-time token;
- an active campaign below its daily limit;
- a verified, non-suppressed contact with a non-placeholder email address;
- current `send_externally` permission and active consent events for every Candidate Fact and
  signature contact actually used by the draft;
- no prior successful real send for the draft revision.

The approval is consumed and the company moves to `sent` only after SMTP succeeds. A provider
failure is stored as a failed attempt and leaves the approval reusable after the cause is
fixed.

## Idempotency and audit

Every send requires a 16–128 character `Idempotency-Key`, unique across delivery requests.
Retrying the same key with the same draft, approval, campaign and mode returns the existing
message without calling SMTP again; reusing it for another request is rejected.

`outbound_messages`, append-only `delivery_attempts`, communication events and audit events
record the outcome. API responses and logs omit message bodies and raw recipient addresses;
they expose a masked recipient, a one-way recipient hash in audit metadata and safe provider
error codes.

## API

- `POST /api/v1/drafts/{draft_id}/send-test`
- `POST /api/v1/drafts/{draft_id}/send`
- `GET /api/v1/messages`

The Review Center exposes only the Mailpit test action. Real send stays API-only so the owner
secret is never entered into or rendered by the web UI.
