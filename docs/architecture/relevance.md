# Deterministic Relevance Scoring

## Boundary

Stage 4 calculates opportunity relevance only from persisted Candidate Profile, company,
research, opportunity and public-contact records. The calculation is deterministic and stores
an immutable `OpportunityAssessment` with the exact input IDs, contribution breakdown,
weights and formula version `opportunity-relevance-v1`.

AI may extract source-backed facts and explain them, but it does not assign or alter numeric
scores. Company size and maturity are descriptive context and never score multipliers. An
active vacancy or strong timing signal can improve relevance, but neither is required for a
non-zero result.

## Dimensions and formula

Every assessment stores these independently visible scores:

- business fit;
- AI/automation fit;
- hybrid fit;
- collaboration-format fit;
- geography fit;
- timing signal;
- contactability;
- overall opportunity relevance.

The default overall score combines core opportunity fit (40%), format (15%), geography (10%),
timing (10%), contactability (10%) and value-proposition realism (15%). The owner may supply
alternative non-negative weights whose sum is exactly 1.0; the chosen values are stored with
the assessment. Every contribution records its deterministic rule, points and supporting IDs.

Thresholds are explicit and exposed through the API: scores at or above 70 identify an
opportunity; scores from 45 through 69.99 require review; lower scores are not relevant. When
company evidence is insufficient, the workflow stays in needs-review regardless of the number.

## Owner override

An owner may override an assessment's effective overall score only through the dedicated
endpoint and must provide a reason. Overrides are append-only records containing original and
replacement scores, actor/request metadata and timestamp. The original assessment is never
rewritten. The effective company score and pipeline relevance status are updated, and the
action is appended to the communication timeline.

## API and UI

Company-scoped API routes expose thresholds, deterministic calculation and override history.
The company detail page can run the calculation, shows formula version, all dimensions,
weighted contributions, source IDs and warnings, and provides the reason-required override
form. Scoring does not approve outreach, generate a draft or bypass any Stage 2 decision gate.
