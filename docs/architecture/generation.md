# Safe Draft Generation

## Stage boundary

Stage 5 creates and stores two first-contact variants only after the owner has explicitly
selected `outreach` for the exact positioning recommendation and the company is in
`approved_for_outreach`. It provides no delivery, publication or export endpoint. Editing and
revision-bound approval are implemented by Stage 6; sending remains a Stage 7 responsibility.

## Inputs and adapter

Generation receives the selected company contact, assessment and positioning recommendation,
verified opportunity types/signals, verified company facts, draft-permitted Candidate Profile
facts and signature contacts, active candidate rules, campaign goal, language, word limits and
prompt version. The adapter returns Pydantic-validated structured output.

The initial provider is the offline `deterministic-local/structured-template-v1` adapter. This
keeps development safe and reproducible while preserving a provider-neutral adapter boundary
for a future explicitly configured model. Runs log entity IDs, provider/model, prompt version,
token estimates and cost, but never the fact pack or draft text in usage logs.

## A/B drafts

Every run produces:

- Variant A — Professional;
- Variant B — Friendly.

Each immutable draft stores subject/body, language decision and confidence, explanation,
positioning and collaboration format, value proposition, all provenance IDs, warnings,
validation report, word count, prompt version and provider/model metadata.

## Deterministic validation

Validation checks the active outreach decision, contact verification/channel/suppression,
verified and permitted fact IDs, verified opportunities/signals, selected positioning and
collaboration format, language, word limits, forbidden content and candidate rules, signature
contacts and evidence for AI-first positioning. Ambiguous language falls back to English with
a review warning. Any block-severity issue persists the draft as `blocked` and leaves the
company outside `draft_ready`; the UI shows every issue.

Only when both A and B pass does the pipeline move from `approved_for_outreach` to
`draft_ready`. This status is not approval of either draft revision.
