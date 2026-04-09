from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.router import api_router
from core.config import settings
from core.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount(
    settings.storage_url_prefix,
    StaticFiles(directory=str(settings.storage_root)),
    name="storage",
)
app.include_router(api_router)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
