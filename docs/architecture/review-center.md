# Revision-safe Review Center

## Review boundary

Stage 6 exposes a dedicated Review Center for the latest Professional/Friendly drafts while
preserving every prior revision. Editing or regenerating never updates text in place: it
creates the next immutable `MessageDraft` row with a new content hash and validation report.
Only the latest revision may be edited, regenerated or receive a review decision.

The page shows company/contact and relevance context, selected positioning, deterministic
validation, revision history, cited sources and current Candidate Fact permissions. Stage 7
adds a Mailpit test-send form; real delivery remains API-only and owner-authenticated.

## Review actions

The owner can explicitly:

- edit or regenerate into a new revision;
- approve the exact current revision;
- defer or reject it;
- mark its company contact do-not-contact.

Every action is written to append-only `draft_review_events` and to the company communication
timeline. Safe diffs contain revision numbers and content hashes, never message text.

## Approval invariant

An approval stores the exact draft ID/revision, owner, timestamp, comment and hash of a random
one-time token. The plaintext token is returned only in the creation response and is never
stored. A database uniqueness constraint permits at most one approval for a draft revision.

Approval validity is fail-closed and requires all of the following:

- it belongs to the latest revision and its content hash still matches;
- it has not been consumed or explicitly invalidated;
- the contact record and verification state have not changed and suppression is absent;
- all cited Candidate Facts remain verified and permitted for draft use;
- deterministic validation still passes.

Creating a new revision permanently invalidates approvals in that variant lineage. Contact
version changes invalidate approval by snapshot mismatch. Revoking Candidate Fact storage or
draft permission explicitly timestamps and permanently invalidates every affected active
approval. Restoring permission cannot revive it; a new revision and new explicit approval are
required.

Stage 6 issues the approval token. Stage 7 re-checks every invariant atomically and consumes
the approval only after a successful real send. Mailpit test sends deliberately leave it
unconsumed.
