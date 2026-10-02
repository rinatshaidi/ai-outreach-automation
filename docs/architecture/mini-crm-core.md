# Opportunity-first Mini-CRM Core

## Aggregate boundaries

`Company` owns public professional `Contact`, optional `JobOpening`, `CompanySource`,
`OpportunitySignal`, `CompanyOpportunity`, `OpportunityAssessment`,
`PositioningRecommendation`, immutable `OpportunityDecisionEvent` and
`CommunicationEvent` records. A vacancy is an optional signal and is never required for an
opportunity.

Mutable records use integer optimistic-lock versions. Company domains and public contact
coordinates are normalized at the API boundary. Verified signals require a source and exact
fragment; verified opportunities require source or signal provenance.

## Opportunity workflow

The pipeline follows the `v1.3` opportunity vocabulary. Transitions are validated against an
explicit graph. A regular company PATCH cannot enter a decision-result state from
`decision_pending`. Only the dedicated owner-decision endpoint can persist `outreach`, `defer`,
`deeper_research`, `not_relevant` or `watchlist` and move the company accordingly.

`APPROVED_FOR_OUTREACH` means only that the owner selected outreach. It does not approve an
email revision. Draft generation remains fail-closed unless both the stored decision is
`outreach` and the company has the corresponding pipeline state.

Every decision is appended to `opportunity_decision_events` and the communication timeline.
Recommendations and assessments remain available after defer or watchlist decisions.

## Assessment boundary

Stage 2 stores all eight `v1.3` scores, formula version, weights, contribution breakdown and
input provenance. Stage 4 adds the deterministic engine and immutable owner overrides. The
legacy Stage 2 UI may still record an explicitly labelled manual assessment; it never claims
that AI or the application calculated that manual score.

## Safety boundary

Contacts contain public professional coordinates only. Verified contacts require a lawful
public-source note and `do_not_contact` remains a first-class block. Stage 5 adds decision-gated
draft generation, but no delivery endpoint and no way to bypass the owner decision or later
revision approval gates. Demo and integration data use synthetic names and reserved `.example`
domains.
