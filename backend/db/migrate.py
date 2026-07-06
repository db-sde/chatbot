from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

from settings import settings


async def run_migrations() -> None:
    db_url = settings.database_url
    try:
        import socket
        host = db_url.split("@")[1].split(":")[0]
        socket.gethostbyname(host)
    except (socket.gaierror, IndexError):
        db_url = db_url.replace("@db:", "@localhost:")
    conn = await asyncpg.connect(dsn=db_url)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        migrations_dir = Path(__file__).parent / "migrations"
        for path in sorted(migrations_dir.glob("*.sql")):
            already = await conn.fetchval("SELECT 1 FROM schema_migrations WHERE version = $1", path.name)
            if path.name == "0001_init.sql" or not already:
                async with conn.transaction():
                    await conn.execute(path.read_text())
                    if not already:
                        await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", path.name)
                print(f"applied/verified {path.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
