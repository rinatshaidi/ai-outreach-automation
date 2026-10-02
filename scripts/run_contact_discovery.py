"""Run bounded Contact Discovery v1 for existing Local Pilot companies only."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.infrastructure.db.session import SessionFactory, close_database
from app.modules.crm.contact_discovery import discover_company_contacts
from app.modules.crm.models import CommunicationEvent, Company

PILOT_COMPANIES = ("Airalo", "Banco Plata", "Bolt", "Einride", "n8n", "what3words")


async def run(selected_name: str | None) -> int:
    names = (selected_name,) if selected_name else PILOT_COMPANIES
    results: list[dict[str, object]] = []
    async with SessionFactory() as session:
        companies = list(
            await session.scalars(
                select(Company).where(
                    Company.name.in_(names),
                    Company.is_synthetic.is_(False),
                )
            )
        )
        by_name = {item.name: item for item in companies}
        for name in names:
            company = by_name.get(name)
            if company is None:
                results.append({"company": name, "status": "missing"})
                continue
            company_id = company.id
            try:
                report = await discover_company_contacts(session, company)
                results.append(
                    {
                        "company": name,
                        "status": report.status,
                        "candidates": report.candidates,
                        "verified_channels": report.verified_channels,
                        "partial_channels": report.partial_channels,
                        "invalid_channels": report.invalid_channels,
                        "search_errors": list(report.search_errors),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - persist and continue the bounded pilot run
                await session.rollback()
                company = await session.get(Company, company_id)
                if company is None:
                    results.append({"company": name, "status": "missing_after_failure"})
                    continue
                company.contact_discovery_status = "failed"
                company.contact_discovered_at = datetime.now(UTC)
                company.version += 1
                session.add(
                    CommunicationEvent(
                        company_id=company.id,
                        event_type="contact_discovery_failed",
                        summary="Contact discovery failed",
                        metadata_json={"error": f"{type(exc).__name__}: {exc}"[:500]},
                    )
                )
                await session.commit()
                results.append(
                    {
                        "company": name,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(item["status"] in {"failed", "missing"} for item in results) else 0


async def async_main(selected_name: str | None) -> int:
    try:
        return await run(selected_name)
    finally:
        await close_database()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", choices=PILOT_COMPANIES)
    args = parser.parse_args()
    return asyncio.run(async_main(args.company))


if __name__ == "__main__":
    raise SystemExit(main())
