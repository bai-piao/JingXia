from fastapi import APIRouter

from api.routes.health import router as health_router
from api.routes.images import router as images_router
from api.routes.upload import router as upload_router
from core.config import settings

api_router = APIRouter(prefix=settings.api_v1_prefix)
api_router.include_router(health_router)
api_router.include_router(images_router)
api_router.include_router(upload_router)
