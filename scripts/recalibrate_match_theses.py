"""Bounded, reviewable refresh of stored company decision briefs.

The script does not search the web, discover contacts, create drafts, send
messages, or export Candidate Profile data.  With ``--allow-ai`` it sends only
already stored public company evidence to the existing synthesis provider so the
selected interface language stays coherent.  The default is a dry run.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

import app.main  # noqa: F401 - register SQLAlchemy models for standalone execution
from app.infrastructure.db.session import SessionFactory
from app.modules.crm.models import Company
from app.modules.research.synthesis import refresh_decision_synthesis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--locale", choices=("ru", "en"), default="ru")
    parser.add_argument("--allow-ai", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not 1 <= args.limit <= 15:
        raise SystemExit("--limit must be between 1 and 15 for a bounded calibration run")

    async with SessionFactory() as session:
        companies = list(
            await session.scalars(
                select(Company)
                .where(
                    Company.is_synthetic.is_(False),
                    Company.pipeline_status.in_(
                        ("decision_pending", "needs_review", "opportunity_identified")
                    ),
                )
                .order_by(Company.updated_at.desc())
                .limit(args.limit)
            )
        )
        if not args.allow_ai:
            print(f"dry_run=1 selected={len(companies)} locale={args.locale}")
            return

        refreshed = 0
        with_match = 0
        contact_pending = 0
        for company in companies:
            synthesis = await refresh_decision_synthesis(session, company, locale=args.locale)
            refreshed += 1
            matches = (synthesis.payload or {}).get("matches", [])
            if matches:
                with_match += 1
            if any(item.get("state") == "match_confirmed_contact_pending" for item in matches):
                contact_pending += 1
        print(
            f"dry_run=0 refreshed={refreshed} with_match={with_match} "
            f"contact_pending={contact_pending} locale={args.locale}"
        )


if __name__ == "__main__":
    asyncio.run(main())
