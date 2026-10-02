"""Create a local profile import preview from ignored JSON without applying it."""

import argparse
import asyncio
import json
from pathlib import Path

from app.api.profile_review import create_profile_import
from app.infrastructure.db.session import SessionFactory, close_database
from app.modules.profile_review.schemas import ProfileImportCreate


async def create_preview(source_path: Path) -> None:
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    payload = ProfileImportCreate.model_validate(raw)
    try:
        async with SessionFactory() as session:
            preview = await create_profile_import(payload, session)
            print(
                json.dumps(
                    {
                        "batch_id": str(preview.id),
                        "status": preview.status,
                        "items": len(preview.items),
                        "validation_report": preview.validation_report,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    asyncio.run(create_preview(args.source.resolve()))


if __name__ == "__main__":
    main()
