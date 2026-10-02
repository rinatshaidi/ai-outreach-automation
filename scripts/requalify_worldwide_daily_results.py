"""Re-evaluate completed worldwide daily-search results after a quality-gate correction.

This deliberately performs no discovery, web fetch, contact lookup, draft
generation or delivery.  It only promotes already researched results that now
meet the corrected worldwide-geography rule, up to the task's existing daily
limit.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

import app.main  # noqa: F401 - register every SQLAlchemy model for standalone execution
from app.infrastructure.db.session import SessionFactory
from app.modules.auth.models import User
from app.modules.crm.models import Company
from app.modules.opportunities.quality import ready_for_inbox
from app.modules.opportunities.readiness import evaluate_opportunity_readiness
from app.modules.research.synthesis import refresh_decision_synthesis
from app.modules.search_tasks.executor import advance_for_owner_decision, link_result, task_audit
from app.modules.search_tasks.models import SearchTask, SearchTaskResult


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True, type=UUID)
    return parser.parse_args()


async def main() -> None:
    task_id = parse_args().task_id
    async with SessionFactory() as session:
        task = await session.get(SearchTask, task_id)
        if task is None:
            raise SystemExit("Search Task was not found.")

        owner = await session.get(User, task.owner_id)
        locale = (
            owner.dashboard_locale
            if owner and owner.dashboard_locale in {"ru", "en"}
            else "en"
        )
        results = list(
            await session.scalars(
                select(SearchTaskResult)
                .where(SearchTaskResult.search_task_id == task.id)
                .order_by(SearchTaskResult.linked_at.asc())
            )
        )

        eligible: list[tuple[float, float, SearchTaskResult, Company]] = []
        synthesized = 0
        for result in results:
            if result.accepted or result.qualification_status != "QUALITY_REVIEW_REQUIRED":
                continue
            company = await session.get(Company, result.company_id)
            if company is None:
                continue
            # The owner uses a Russian interface while most worldwide public
            # sources are English.  Recreate the brief through the configured
            # public-evidence provider so the language guard remains truthful;
            # no candidate profile, web search or contact lookup is sent.
            synthesis = await refresh_decision_synthesis(session, company, locale=locale)
            synthesized += 1
            readiness = await evaluate_opportunity_readiness(session, company, locale=locale)
            if ready_for_inbox(
                company, synthesis.payload, readiness.contact_status == "CONTACT_FOUND"
            ):
                eligible.append(
                    (
                        company.overall_opportunity_score or 0.0,
                        company.relevance_score or 0.0,
                        result,
                        company,
                    )
                )

        available_slots = max(0, task.result_limit - task.accepted_count)
        eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = eligible[:available_slots]

        for _, _, result, company in selected:
            company = await advance_for_owner_decision(session, company)
            # The other dashboard language remains a deterministic fallback;
            # no extra provider call is needed for this repair.
            await refresh_decision_synthesis(
                session,
                company,
                locale="en" if locale == "ru" else "ru",
                allow_ai=False,
            )
            evidence = dict(result.qualification_evidence or {})
            evidence["worldwide_geography_requalified"] = True
            await link_result(
                session,
                task,
                company,
                accepted=True,
                qualification_status="QUALIFIED",
                qualification_evidence=evidence,
            )

        await session.refresh(task)
        task.failure_code = None
        task.failure_reason = (
            f"Completed with {task.accepted_count} of {task.result_limit} requested results"
            if task.accepted_count < task.result_limit
            else None
        )
        task_audit(
            session,
            task,
            "search_task_worldwide_geography_requalified",
            safe_diff={
                "eligible_results": len(eligible),
                "promoted_results": len(selected),
                "accepted_count": task.accepted_count,
                "result_limit": task.result_limit,
            },
        )
        await session.commit()

    print(
        f"synthesized={synthesized} eligible={len(eligible)} promoted={len(selected)} "
        f"accepted={task.accepted_count} limit={task.result_limit}"
    )


if __name__ == "__main__":
    asyncio.run(main())
