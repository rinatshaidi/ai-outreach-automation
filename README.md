# Single Outreach

Single Outreach is a single-owner career-outreach application. It continuously finds real companies and vacancies that may fit the owner's verified professional profile, turns public evidence into a clear decision brief, and prepares a message only after the owner decides that the opportunity is worth pursuing.

It is a working application, not a lead list or a generic email generator.

## What the product does

- Runs scheduled daily discovery and accepts ordinary-language manual searches.
- Researches official company sources, current vacancies and material public signals.
- Explains the fit in practical terms: the company context, the owner's relevant experience, the possible contribution and the main limitation.
- Separates a confirmed vacancy from a wider collaboration hypothesis.
- Shows only the best available contact paths: a named founder, CEO or hiring contact when verified; otherwise an honestly labelled official company channel.
- Creates four editable drafts for the selected contact: long/short × professional/friendly.
- Keeps draft revisions, company decisions and activity history inside the same company workspace.
- Supports Russian and English interfaces, responsive layouts and Moscow-time user-facing dates.

The core workflow is:

```text
Daily or manual search
  → evidence-based company review
  → fit and contact check
  → owner decides whether the company is interesting
  → draft preparation and editing
  → explicit draft confirmation
  → manual copy-out or separately enabled delivery
```

Opening a company is not a decision. Confirming a company and confirming a specific draft are separate actions.

## Safety by design

- Research links are not presented as personal contacts.
- A message is never sent merely because a draft exists.
- Real external delivery is disabled in the default configuration and requires separate server-side safeguards and owner confirmation.
- Local development uses Mailpit only; it never sends to a real mailbox.
- Production secrets, OAuth tokens, profile data and local `.env` files are excluded from Git and must not appear in logs or UI.
- Uncertain or incomplete research is shown as uncertainty rather than invented detail.

## Local development

Requirements: Python 3.12+ and PostgreSQL, or Docker Compose.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

For Docker development:

```powershell
docker compose --profile dev up --build
```

- Application: `http://localhost:8000`
- Local test mailbox (Mailpit): `http://localhost:8025`

Create the local owner only after the database migration:

```powershell
python scripts/create_owner.py --login owner
```

The script asks for the password interactively; it is never supplied as a command-line argument.

## Verification

```powershell
ruff check app tests migrations scripts
mypy app
pytest -q
```

The GitHub Actions workflow runs linting, typing, migrations and the PostgreSQL regression suite. The repository contains synthetic examples only; do not add production database dumps, delivery archives, screenshots with personal data or secrets.

## Repository map

- `app/` — FastAPI application, research, fit, contacts, draft and safety modules.
- `migrations/` — Alembic schema history.
- `tests/` — unit and integration regression coverage.
- `scripts/` — local and production operational helpers; secrets are always entered interactively or supplied through protected environment configuration.
- `docs/architecture/` — implementation notes.
- `docs/production/` — deployment and security runbooks.

The project is licensed under the [MIT License](LICENSE).
