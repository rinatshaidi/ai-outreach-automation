# Safe Research

## Boundary

Stage 3 accepts a manually supplied public HTTP/HTTPS URL and never executes instructions
found in retrieved content. Research is company-scoped and stores a `ResearchRun`, deduplicated
`CompanySource`, extracted `CompanyFact`, proposed `OpportunitySignal`, proposed
`CompanyOpportunity` and explicitly labelled `CompanyTaskHypothesis` records.

An active vacancy is optional. When no strong signal is present, deterministic extraction may
propose `GENERAL_COMPETENCE_FIT`; it does not mark the hypothesis as a fact or automatically
approve outreach.

## Network safety

The fetcher applies:

- HTTP/HTTPS-only normalized URLs without userinfo or fragments;
- standard ports only;
- DNS validation blocking private, loopback, link-local, metadata, multicast, reserved and
  unspecified addresses;
- target revalidation after every bounded redirect;
- robots.txt enforcement;
- per-host rate limiting;
- explicit request timeout;
- HTML/plain-text allowlist;
- streaming response-size limit;
- bounded redirect count.

CAPTCHA, authentication, paywalls, hidden APIs and whole-site crawling are not bypassed.

## Extraction and review

HTML scripts, styles, SVG and page instructions are discarded. The deterministic extractor
records visible text, language, exact fragments and conservative confidence. Rule-derived
signals remain `extracted`; opportunity classifications remain `proposed`; task hypotheses
must include an explicit risk and require user review.

Public `mailto` links may create deduplicated professional contacts, always initially
`unverified`. No address pattern guessing occurs. Research cannot generate or send messages.

Repeated research of the same URL updates source freshness/hash and creates a new run without
duplicating facts, signals, opportunities, hypotheses or public contacts.
