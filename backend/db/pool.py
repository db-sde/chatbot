from __future__ import annotations

import asyncpg

from settings import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        db_url = settings.database_url
        try:
            import socket
            host = db_url.split("@")[1].split(":")[0]
            socket.gethostbyname(host)
        except (socket.gaierror, IndexError):
            db_url = db_url.replace("@db:", "@localhost:")
        _pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=10)
    return _pool


async def get_pool() -> asyncpg.Pool:
    return await init_pool()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
