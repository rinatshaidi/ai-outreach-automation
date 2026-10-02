"""Refresh owner-facing categories for contacts in the active company inbox.

No web requests, AI calls, email generation or delivery are performed.  The
script derives the category only from existing public contact records.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

import app.main  # noqa: F401 - register every SQLAlchemy model for standalone execution
from app.infrastructure.db.session import SessionFactory
from app.modules.crm.contact_validation import classify_contact_for_outreach
from app.modules.crm.models import Company, Contact


async def main() -> None:
    async with SessionFactory() as session:
        companies = list(
            await session.scalars(
                select(Company)
                .where(Company.pipeline_status == "decision_pending")
                .options(selectinload(Company.contacts).selectinload(Contact.channels))
            )
        )
        updated = 0
        for company in companies:
            for contact in company.contacts:
                before = (
                    contact.name,
                    contact.role,
                    contact.decision_maker_role,
                    contact.decision_priority,
                    contact.do_not_contact,
                    contact.why_relevant,
                )
                classify_contact_for_outreach(contact, company.name)
                after = (
                    contact.name,
                    contact.role,
                    contact.decision_maker_role,
                    contact.decision_priority,
                    contact.do_not_contact,
                    contact.why_relevant,
                )
                if before != after:
                    contact.version += 1
                    updated += 1
        await session.commit()
    print(f"companies={len(companies)} contacts_updated={updated}")


if __name__ == "__main__":
    asyncio.run(main())
