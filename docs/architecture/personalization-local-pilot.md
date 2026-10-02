# Personalization and local pilot

Stage 10 runs only on localhost with FastAPI, PostgreSQL, Dashboard and Mailpit. Its invariant is
that technical automation may propose data and drafts but cannot confirm identity claims,
permissions, outreach decisions, delivery or production readiness.

## Authentication boundary

`User` is a single-owner account with an Argon2id password hash. `AuthSession` stores only a hash
of an opaque cookie token and has an expiry/revocation state. `LoginAttempt` records safe result
codes for rate limiting and audit. Anonymous browser requests redirect to `/login`; anonymous API
requests receive 401. Unsafe methods additionally require double-submit CSRF validation.

There is no registration endpoint. Credentials are created or rotated interactively:

```powershell
python scripts/create_owner.py --login owner
python scripts/create_owner.py --login owner --rotate
```

## Profile review

Every primary profile has exactly 23 semantic `CandidateProfileSection` rows. The allowed normal
transition is `draft/review_required -> user_approved -> verified`. Corrections invalidate prior
approval, increment the section version and return it to review. Every decision produces a
`ProfileReviewEvent` without copying sensitive values into audit metadata.

Profile records carry purpose-specific permissions, including `use_in_scoring` and
`use_in_signature`. Defaults are false. Verification and permissions cannot be activated by an
import payload.

## Structured import

The JSON flow is explicit:

1. Upload creates a `preview_ready` batch and proposed items only.
2. Validation classifies create, match or conflict and reports ignored permission requests.
3. The owner approves, rejects, skips or corrects each item.
4. Apply creates only approved non-conflicting records.

Apply never overwrites, deletes, merges, verifies or enables downstream permissions implicitly.
Applied sections return to `review_required`.

## Pilot boundary and completion

The Dashboard and `GET /api/v1/pilot/readiness` expose safe counts, not profile values. Calibration
notes are version-labelled and may reference a company. During Stage 10:

- `DEMO_MODE=true`;
- `ALLOW_REAL_EMAIL=false`;
- `ALLOW_PUBLICATION=false`;
- `ALLOW_EXTERNAL_EXPORT=false`;
- every test delivery targets Mailpit;
- no tunnel, VPS, domain, push or production SMTP is introduced.

Technical tests are necessary but insufficient. Completion requires owner-approved mandatory
profile blocks, a 3–5-company first wave, calibration, a cycle of up to 10 companies, acceptable
scoring/positioning and explicit owner acceptance.
