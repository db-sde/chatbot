import logging
import re
import asyncio
import asyncpg

from settings import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


class DatabaseConnectionError(Exception):
    """Raised when the application cannot connect to the database."""
    pass


def _sanitize_dsn(dsn: str) -> str:
    """Mask the password in the connection string for safe logging."""
    return re.sub(r":([^@/]+)@", r":***@", dsn)


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
        
        sanitized_url = _sanitize_dsn(db_url)
        logger.info("Initializing database pool at %s", sanitized_url)

        last_exc = None
        for attempt in range(1, 6):
            try:
                _pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=10)
                logger.info("Database pool initialized successfully on attempt %d", attempt)
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Database connection attempt %d/5 failed for %s. Error: %s",
                    attempt,
                    sanitized_url,
                    exc,
                )
                if attempt < 5:
                    await asyncio.sleep(1)
        
        if _pool is None:
            err_msg = f"Failed to connect to database at {sanitized_url} after 5 attempts."
            logger.critical(err_msg, exc_info=last_exc)
            raise DatabaseConnectionError(err_msg) from last_exc
            
    return _pool




async def get_pool() -> asyncpg.Pool:
    return await init_pool()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
