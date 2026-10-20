"""Durable, at-least-once CRM delivery outside the visitor's request."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from db.pool import get_pool

logger = logging.getLogger(__name__)


async def deliver_next(pool, client: httpx.AsyncClient) -> bool:
    row = await pool.fetchrow(
        """
        WITH candidate AS (
            SELECT id FROM crm_deliveries
            WHERE (status = 'pending' AND next_attempt_at <= now())
               OR (status = 'processing' AND locked_at < now() - interval '60 seconds')
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
        )
        UPDATE crm_deliveries d SET status='processing', locked_at=now(),
            claim_token=gen_random_uuid(), attempts=attempts+1, updated_at=now()
        FROM candidate WHERE d.id=candidate.id RETURNING d.*
        """
    )
    if not row:
        return False
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    status_code = None
    try:
        response = await client.post(
            row["webhook_url"], json=payload,
            headers={"Idempotency-Key": f"degreebaba-crm-{row['id']}"},
        )
        status_code = response.status_code
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Do not log webhook URLs, response bodies or contact information.
        retry_seconds = min(3600, 2 ** min(row["attempts"], 12))
        await pool.execute(
            """UPDATE crm_deliveries SET status='pending', next_attempt_at=now()+$3*interval '1 second',
               last_status_code=$4, last_error=$5, updated_at=now()
               WHERE id=$1 AND claim_token=$2""",
            row["id"], row["claim_token"], retry_seconds, status_code, type(exc).__name__,
        )
        logger.warning("CRM delivery %s will retry (HTTP status=%s)", row["id"], status_code)
    else:
        await pool.execute(
            """UPDATE crm_deliveries SET status='delivered', last_status_code=$3,
               last_error=NULL, updated_at=now() WHERE id=$1 AND claim_token=$2""",
            row["id"], row["claim_token"], status_code,
        )
    return True


async def run_delivery_worker() -> None:
    async with httpx.AsyncClient(timeout=8) as client:
        while True:
            try:
                worked = await deliver_next(await get_pool(), client)
            except Exception:
                logger.exception("CRM delivery worker will retry after a database error")
                worked = False
            await asyncio.sleep(0.25 if worked else 2)
