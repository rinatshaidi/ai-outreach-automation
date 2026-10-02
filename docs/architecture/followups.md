# Guarded follow-up and communication history

## Scheduling boundary

A follow-up is scheduled only after a successful `real` outbound message. Test messages and
failed delivery attempts never create one. The campaign policy defaults to one follow-up
after five business days; the calculation uses the required IANA `USER_TIMEZONE` and stores
the resulting UTC timestamp together with the timezone name.

The lifecycle is:

```text
PLANNED → DUE → DRAFT_READY → APPROVED | DEFERRED | REJECTED | CANCELLED
```

`POST /api/v1/followups/refresh-due` claims due rows with database locks and creates a
deterministic proposal. The proposal is shorter than the original email, references no new
Candidate Facts, stores its content hash and validation report, and explicitly records that
automatic sending is forbidden. An invalid proposal cannot be approved.

Approval is explicit and optimistic-lock protected. It authorizes only the exact proposal;
Stage 8 does not add an automatic or background send path. Deferral requires a future,
timezone-aware due timestamp.

## Automatic cancellation

Every open follow-up, including an approved but unsent proposal, is cancelled when its
context is no longer eligible:

- a manual reply or outcome is recorded;
- the company reaches replied, interview, project/consulting discussion, rejected, offer,
  agreement or closed;
- the contact becomes suppressed or do-not-contact;
- the campaign is no longer active;
- due refresh detects missing or ineligible delivery context.

Cancellation is stored with a safe reason and is written to both communication history and
audit.

## Manual replies and unified history

`POST /api/v1/communications/replies` records an owner-entered summary and one structured
outcome: reply, interview, project discussion, consulting discussion, rejection, offer or
agreement. The contact must belong to the company. In the same transaction the endpoint
updates the company pipeline and cancels all open follow-ups.

The existing communication timeline therefore combines discovery, research, decisions,
drafts, approvals, delivery, follow-up proposals/decisions/cancellations and manually
recorded outcomes. No inbound mailbox polling or automatic reply classification exists in
the MVP.
