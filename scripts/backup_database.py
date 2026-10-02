"""Create a local gzip-compressed JSON snapshot of the configured PostgreSQL database."""

import argparse
import asyncio
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.infrastructure.db.session import engine


def json_default(value: Any) -> str:
    return str(value)


async def create_backup(destination: Path) -> dict[str, int]:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        table_names = list(
            (
                await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' ORDER BY table_name"
                    )
                )
            ).scalars()
        )
        tables: dict[str, list[dict[str, Any]]] = {}
        for table_name in table_names:
            quoted_name = table_name.replace('"', '""')
            result = await connection.execute(text(f'SELECT * FROM "{quoted_name}"'))  # noqa: S608
            tables[table_name] = [dict(row) for row in result.mappings()]

    payload = {
        "created_at": datetime.now(UTC),
        "alembic_revision": revision,
        "tables": tables,
    }
    with gzip.open(destination, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, default=json_default, sort_keys=True)

    await engine.dispose()
    return {name: len(rows) for name, rows in tables.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    counts = asyncio.run(create_backup(args.destination.resolve()))
    print(json.dumps({"destination": str(args.destination.resolve()), "counts": counts}))


if __name__ == "__main__":
    main()
