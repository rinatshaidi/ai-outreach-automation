# Stage 10 — Personalization and Local Pilot

## Final status

**DONE**

The Local MVP has demonstrated the complete safe workflow:

`REAL CANDIDATE PROFILE → COMPANY RESEARCH → OPPORTUNITY → PUBLIC CONTACT → DRAFT → OWNER DECISION → MAILPIT TEST SEND`

The final verification found no Stage 10 blocker. No production delivery, external publication, export, or deployment was performed.

## Environment

- Date of final verification: 2026-08-10 (Europe/Moscow).
- Alembic revision: `20260810_0019 (head)`.
- Docker services: application, PostgreSQL, and Mailpit healthy.
- PostgreSQL: accepting connections.
- FastAPI readiness endpoint: HTTP 200.
- Mailpit API: HTTP 200.
- Runtime: development / local demo mode.
- Real SMTP: OFF (`allow_real_email=false`, Mailpit-only SMTP host).
- Auto-send: OFF; every delivery requires an explicit owner action.
- Publication: OFF (`allow_publication=false`).
- External export: OFF (`allow_external_export=false`).
- Authentication: ON in the working application.
- AI Rewrite provider: `unavailable` (honest fail-closed state; no fake rewrite).

## Candidate Profile

- Computed working-app status: `READY_FOR_LOCAL_PILOT`.
- 23 semantic blocks: 23 `user_approved`.
- Professional experience: 3/3 VERIFIED.
- Skills: 4/4 VERIFIED.
- Strengths: 8/8 VERIFIED.
- Candidate facts: 6/6 VERIFIED.
- Candidate contacts: 3/3 VERIFIED.
- Active generation rules: 6.
- Permissions used by the Local Pilot:
  - local storage: ON;
  - AI analysis: ON;
  - scoring: ON;
  - draft generation: ON;
  - external send: OFF;
  - signature: OFF;
  - publication: OFF.

The real structured profile is used in scoring and draft generation. No further mandatory profile action is required for the Local Pilot. The stored `profile_status` field remains `draft`, but the authoritative computed readiness is `READY_FOR_LOCAL_PILOT`; it is based on approved semantic blocks, verified structured records, permissions, authentication, and safe runtime flags.

## Local Pilot Companies

Six real companies and three synthetic companies remain stored separately. Synthetic records were not used as real pilot results.

### Banco Plata

- Scenario: direct-company analysis in Mexico; business / operations / hybrid positioning.
- Research: 5 sources, 6 company facts, opportunity-first assessment completed.
- Opportunity: identified; score 80.23.
- Contact: Banco Plata Hiring Team, verified public recruitment path; support contacts remain suppressed.
- Draft: Professional and Friendly variants with revision history; selected Professional revision 7.
- Owner state: approved.
- Final result: Professional revision 7 test-sent to Mailpit; no real delivery.
- Main finding: the complete owner-confirmed delivery path works and preserves all CRM links.

### Airalo

- Scenario: concrete Business Development / Partnerships public contact.
- Research: 5 sources, 3 facts, 3 verified opportunities.
- Opportunity: business expansion / operations / active hiring; owner review remains appropriate.
- Contact: official partnership form, HTTP 200 and VERIFIED.
- Draft: Professional revision 3 and Friendly revision 2 are `ready` and pass validation.
- Owner state: current revised pair requires review; one earlier revision was test-sent through Mailpit.
- Main finding: official business channels work without inventing a named decision-maker.

### n8n

- Scenario: AI / technology company with careers context.
- Research: official careers/product context, 2 facts, 3 verified opportunities.
- Opportunity: AI orchestration, process automation, and hybrid delivery fit.
- Contact: official Talent Acquisition / Careers path, HTTP 200 and VERIFIED.
- Draft: Professional revision 3 and Friendly revision 3 are `ready` and pass validation.
- Owner state: review.
- Main finding: AI-first positioning stays honest about junior technical depth and uses the owner's management background.

### what3words

- Scenario: no assumed internal vacancy need; opportunity hypothesis based on public Business Development and Customer Operations context.
- Research: official careers/company source, 2 facts, 3 verified opportunities.
- Opportunity: operations improvement / competence fit / consulting hypothesis; score 74.
- Contact: official careers path, HTTP 200 and VERIFIED.
- Draft: Professional and Friendly variants are `ready` and pass validation.
- Owner state: deferred; the existing owner decision was preserved.
- Main finding: a valid company can remain intentionally deferred without being sent or lost.

### Bolt

- Scenario: expansion / global operations and a public Expansion Lead context.
- Research: official source HTTP 200, one fact, three verified opportunities.
- Opportunity: open vacancy, expansion, and operations improvement.
- Contact: official Business Development / Partnerships path, VERIFIED.
- Draft: Professional and Friendly variants exist and are ready.
- Owner state: review.
- Main finding: a specific expansion role can be compared with transferable launch and project experience.

### Einride

- Scenario: new-industry transferable fit in electric/autonomous freight.
- Research: official source, 2 facts, 4 verified opportunities; deeper research recorded.
- Opportunity: scored 69.15, but this does not override the owner's judgment.
- Contact: official public company contact, VERIFIED.
- Draft: not created.
- Owner state: `not_relevant`.
- Main finding: the system can reject an apparently plausible company before draft generation.

## Contact Discovery

- Real companies with at least one verified non-suppressed public contact path: 6/6.
- Real companies without a verified public path: 0.
- Airalo, n8n, and what3words calibration paths were rechecked against their official public pages and resolve successfully.
- Invalid/unverified personal paths are not selected as primary contacts.
- Customer-support addresses marked `do_not_contact` remain excluded.
- An email address is not required when an official form or careers path is valid.

## Draft / Review

- Total draft revisions: 39.
- Ready revisions: 34.
- Independent variant lineages: 14 across 5 real companies.
- Professional and Friendly variants are present for the calibration companies.
- Manual edits create append-only revisions and audit events.
- Revision history, restoring an older revision, owner confirmation, defer/restore, and do-not-send states are available.
- Letters are separated into Drafts, Deferred, Sent, Replies, and Follow-ups.
- RU/EN dashboard locale switches correctly and remains independent of outreach language.
- AI Rewrite without a configured provider displays a clear error and creates no revision.

Stage 10 quality corrections:

- Removed internal word `verified` and robotic template phrases from current Airalo and n8n drafts.
- The new revisions are company-specific, English-language, 124–147 words, and pass the current validator.
- No draft was generated or sent automatically.

## Mailpit E2E

### Final Banco Plata test

- Company: Banco Plata.
- Linked contact: Banco Plata Hiring Team (Talent Acquisition / Careers).
- Draft: `afa91ce2-e194-4970-9934-88d3594185f9`, Professional variant A, revision 7.
- Subject: `A possible fit with Banco Plata`.
- Test recipient: `mailpit@example.test`.
- From: `AI Outreach System <outreach@example.test>`.
- Timestamp: `2026-08-10 20:09:59 UTC`.
- Delivery: `test / sent`, provider `smtp` through local Mailpit.
- Mailpit message ID: `2aaC0yh4ayODciW2mEyOSC`.
- Application message ID: `ec0a90d7-0383-4b83-8815-da7407c0b522`.
- Encoding: subject and English plain-text body verified intact; CRLF/UTF-8 rendering correct.
- Links preserved: company, contact, campaign, exact draft revision, approval, assessment and opportunity IDs.
- Delivery attempt: created and marked `sent`.
- Timeline event: `test_email_sent` / `Test email delivered to Mailpit`.
- UI result: `Тестово отправлено через Mailpit`, not “sent to company”.
- Company pipeline remains `approved`; next action explicitly states that real email was not sent.
- Approval was not consumed by the test send.
- Follow-ups created: 0.
- Real mailbox reply wait: not started.

The database also retains an earlier successful Airalo Mailpit test. Total successful test-mode messages in application history: 2. Total real-mode messages: 0. The current Mailpit inbox contains the final Banco Plata message; Mailpit is an ephemeral local inbox, while application delivery history is durable in PostgreSQL.

## Search Task

- Manual Search Task UI and API exist.
- `original_query` is stored unchanged and separately from detected query language.
- The existing Russian query for `plata` completed successfully and is linked to Banco Plata.
- Direct company analysis is implemented.
- Search Tasks do not mutate Candidate Profile settings.
- Task/result linking and failure state fields are present and covered by integration tests.
- No new search wave was started during completion verification.

## User Interface Smoke Test

Verified through the local owner workflow:

- Selected companies list and Search Task panel;
- company card;
- research/opportunity presentation;
- found contacts and selectable verified channel;
- prepare-letter path;
- Drafts, Deferred, and Sent tabs;
- review detail and revision history;
- manual editing;
- AI Rewrite unavailable state;
- Candidate Profile and final verification screen;
- My Profile;
- Settings;
- RU/EN switch.

No HTTP 500, broken route, data loss, broken permission gate, or workflow blocker was found.

## Verification Results

- Targeted Search Task / CRM / HTTP suite: **27 passed**.
- Full regression suite: **134 passed**.
- Ruff: passed.
- mypy (strict): passed for 91 source files.
- FastAPI import/route smoke: passed.
- Docker / PostgreSQL / Mailpit health: passed.

Non-blocking test-environment warnings:

- `pytest-asyncio` uses event-loop-policy APIs deprecated for future Python 3.16.
- Pytest could not refresh one cache file because an existing local cache path is locked/malformed. Test execution and results were not affected.

## Known limitations

- **KNOWN CONFIGURATION LIMITATION:** real AI Rewrite requires `OPENAI_API_KEY` and `AI_REWRITE_PROVIDER=openai`. Without them the UI fails closed and creates no fake revision.
- A real mailbox, production SMTP, inbound reply processing, and real reply detection are not configured.
- Production-grade automatic discovery at approximately 10 companies/day is not validated for unattended operation.
- Mailpit inbox storage is local/ephemeral; durable delivery history is stored in PostgreSQL.
- `profile_status` remains a separate editable profile field; Local Pilot readiness is the computed safety status described above.

These limitations do not block the Local MVP or the Stage 10 completion criteria.

## Deferred

Intentionally deferred to Stage 11 or later:

- production decision and production architecture;
- VPS, domain, HTTPS, deployment and monitoring;
- production SMTP and mailbox integration;
- inbound email/reply synchronization;
- real seven-business-day follow-up proposal timing;
- any real external delivery;
- production-grade scheduled discovery;
- large Candidate Profile UI redesign;
- SaaS / multi-user architecture;
- external exports and publication.

## Security

Final safety confirmation:

- real send: OFF;
- auto-send: OFF;
- real follow-up send: OFF;
- publication: OFF;
- external export: OFF;
- production SMTP credentials: absent;
- external channel delivery: not performed;
- owner approval remains mandatory;
- test sends are Mailpit-only and are labelled as tests.

## Recommendation

**READY_FOR_STAGE_11 = YES**

Reason: Stage 10 has demonstrated the intended value and safety boundary with real profile data and real public company research. A company can be researched, evaluated, matched to an owner profile, connected to a lawful public contact path, converted into company-specific drafts, reviewed through revisions, deferred or rejected, explicitly approved, and test-delivered to Mailpit without any real external send or automatic follow-up.

Stage 11 must begin only after a separate owner instruction. No deployment, production integration, or real send is authorized by this report.
