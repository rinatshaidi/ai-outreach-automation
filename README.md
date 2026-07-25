# AI Outreach Automation

Minimal, auditable tooling for preparing B2B outreach lead lists.

The project validates lead data, records evidence for personalization, and
produces review-ready exports. It does not send emails.

## Status

The first working script is ready. It runs safely offline by default and never
sends email.

## Principles

- Keep source links alongside personalization facts.
- Treat generated text as a draft, not as evidence.
- Keep credentials and real lead exports out of version control.
- Require human review before external use.

## Planned workflow

1. Load a CSV of companies.
2. Validate fields and flag questionable rows.
3. Generate source-grounded personalization drafts.
4. Export approved rows for spreadsheet review.

## Development

```powershell
python personalize.py --input examples/leads.sample.csv --output output/leads.checked.csv
python -m unittest discover -s tests
```

The same test command can be run locally before publishing changes.

Add `--llm` only after setting `LLM_API_KEY` and `LLM_MODEL` in a local `.env`
file or shell environment. In that mode the script reads only the row's public
`source_url`, requests a short draft, and retains the source URL in the output.

## Input format

Required columns: `company`, `website`, `email`.

Optional columns: `source_url`, `personalization`. The output additionally
contains `audit_status`, `audit_details`, and `error`.

## Data policy

Only synthetic examples belong in this repository. Real contact data, API keys,
and private exports must remain local.
