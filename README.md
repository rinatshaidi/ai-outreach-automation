# Single Outreach

Single-user portfolio application for finding real companies and current vacancies that may fit an owner's verified professional profile.

It turns public research into a reviewable decision: **company → evidence → fit → verified public contact → draft → owner confirmation**. The system does not treat a research link as a contact, does not claim a vacancy without a source, and never sends externally without an explicit owner decision.

## What it demonstrates

- Background discovery of real companies with official-source research.
- Evidence-linked company fit and explicit uncertainty/risk presentation.
- Current-vacancy review distinct from a non-vacancy collaboration hypothesis.
- Ranked public contact paths: named founder/CEO/HR where supported, otherwise an honestly labelled company channel.
- Four editable message variants: long/short × professional/friendly.
- Draft revisions, owner decisions, deferred/closed states and a company-centred activity history.
- RU/EN interface, responsive workspace, audit trail and fail-closed delivery controls.

## Product workflow

1. A manual search or daily worker discovers a bounded pool of companies.
2. The executor verifies the official site, records public evidence, evaluates fit and finds public contact paths.
3. Only quality-checked opportunities enter **Selected companies**.
4. Opening a card marks it reviewed without approving it. The owner may return it to new, reject it, or confirm interest.
5. Confirming interest prepares drafts for a selected verified contact. Confirming a draft is separate from the company decision.
6. The owner may copy the text or use an explicitly enabled delivery channel. Real delivery remains disabled by default.

## Local run

Requirements: Python 3.12+ and PostgreSQL, or Docker Compose.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://localhost:8000`. In Docker development, run:

```powershell
docker compose --profile dev up --build
```

- App: `http://localhost:8000`
- Mailpit test inbox: `http://localhost:8025`

Create the local owner interactively after migrations:

```powershell
python scripts/create_owner.py --login owner
```

The password is never passed as a command-line argument. Use `--rotate` only when intentionally changing credentials and revoking sessions.

## Safety and data boundaries

- Only synthetic demo data may be committed.
- Candidate facts are private and require explicit per-purpose permission.
- Public company material may be used for research; owner profile data is not sent to the company-synthesis provider.
- Demo mode and external delivery are off by default. Mailpit is for local testing only.
- Production secrets belong in protected environment configuration, never Git, UI or logs.

## Demo

Run `python scripts/seed_demo.py` only in demo mode to load reserved `.example` records. A useful portfolio walkthrough is: open a selected company, inspect its evidence and fit, identify the labelled public contact, create the four drafts, edit one, view history, confirm it, and stop before any external send.

## Checks

```powershell
ruff check .
mypy app
pytest
```

The CI quality workflow runs linting, typing, migrations and the PostgreSQL regression suite. Architecture notes under `docs/architecture` describe individual modules; they are implementation references rather than a promise that every optional integration is enabled in a deployment.
