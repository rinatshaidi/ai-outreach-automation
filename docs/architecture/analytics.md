# Opportunity analytics and portfolio

## Read model

Stage 9 adds a read-only analytics layer over the normalized CRM, research, opportunity,
generation, delivery, follow-up and communication tables. It does not copy aggregates into a
new table, so the report reflects the current source records and needs no migration.

`GET /api/v1/analytics` returns:

- opportunity, positioning, review, delivery, follow-up and outcome KPI;
- a current-stage opportunity funnel;
- breakdowns by opportunity type, positioning, vacancy, company size/maturity, country,
  collaboration/workplace format, first decision-maker, source trust/freshness, pipeline,
  owner decision and outcome;
- an opportunity portfolio with score, active-vacancy flag, contactability, drafts, real
  delivery, follow-up and next action.

Repeated messages do not multiply company-level opportunity or outcome counts. Message,
draft and approval metrics remain record counts because those objects are themselves the
measured unit.

## Filters and interpretation

Filters are applied in SQL before aggregation and portfolio construction. Array dimensions
use PostgreSQL containment, while vacancy, contact, source and owner-decision dimensions use
correlated existence checks. The UI exposes common filters directly and all supported
dimensions through its advanced section.

Company size and maturity are descriptive breakdowns only. They do not enter relevance
scoring and never create an automatic penalty. Likewise, vacancy is a separate dimension:
`GENERAL_COMPETENCE_FIT`, automation and project opportunities without a vacancy remain
visible in KPI, funnel and portfolio.

The average stage time is the mean elapsed time from company creation to the current record
stage for processed companies. It is labelled accordingly and is not presented as a causal
performance measure.

## Product objective

The dashboard intentionally emphasizes recommendation quality, explicit owner decisions and
positive outcomes. It does not optimize for maximum sending volume. The synthetic demo
contains vacancy and non-vacancy companies, all three positioning strategies, a large mature
company with a strong score and a project-discussion outcome.
