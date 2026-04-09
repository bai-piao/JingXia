from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, Response, status as http_status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


async def _check_db(session: AsyncSession) -> str:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check failed while probing database.")
        return "error"
    return "ok"


async def _check_ai() -> str:
    base_url = f"{settings.ai_api_base_url.rstrip('/')}/"
    timeout = httpx.Timeout(3.0, connect=3.0)

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            response = await client.get("models")
            response.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL):
        logger.exception("Health check failed while probing AI service: %s", base_url)
        return "error"
    return "ok"


@router.get("/health")
async def health(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    db_status = await _check_db(session)
    ai_status = await _check_ai()

    if db_status == "ok" and ai_status == "ok":
        overall_status = "ok"
        response.status_code = http_status.HTTP_200_OK
    elif db_status == "ok":
        overall_status = "degraded"
        response.status_code = http_status.HTTP_200_OK
    else:
        overall_status = "error"
        response.status_code = http_status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall_status,
        "db": db_status,
        "ai": ai_status,
    }
