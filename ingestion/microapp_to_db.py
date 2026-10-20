from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import asyncpg

from settings import settings
from money import parse_money


# Keep the existing CLI/import API while sharing the SQL implementation.
from catalog.importer import (
    detect_type, pick, rebuild_search_index, replace_common_children, slugify,
    upsert_university, upsert_course, upsert_specialization,
)


async def ingest(path: Path, explicit_type: str | None) -> tuple[str, int]:
    payload = json.loads(path.read_text())
    entity_type = explicit_type or detect_type(payload)
    conn = await asyncpg.connect(settings.database_url)
    try:
        async with conn.transaction():
            if entity_type == "university":
                return await upsert_university(conn, payload)
            if entity_type == "course":
                return await upsert_course(conn, payload)
            if entity_type == "specialization":
                return await upsert_specialization(conn, payload)
            raise ValueError(f"Unknown type: {entity_type}")
    finally:
        await conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--type", choices=["university", "course", "specialization"])
    args = parser.parse_args()
    slug, entity_id = await ingest(args.json_path, args.type)
    print(f"upserted {slug} ({entity_id})")


if __name__ == "__main__":
    asyncio.run(main())
