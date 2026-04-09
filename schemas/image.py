from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from core.config import settings


class ImageRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    local_path: str
    url_path: str
    ocr_text: str | None = None
    tags: list[str] | None = None
    created_at: datetime


class ImageListRead(BaseModel):
    items: list[ImageRecordRead]
    total: int
    page: int
    page_size: int
    debug_terms: list[str] | None = None
    debug_source: str | None = None


def build_public_file_url(raw_url_path: str) -> str:
    normalized = raw_url_path.strip()
    if not normalized:
        return ""

    if normalized.startswith(("http://", "https://")):
        parsed = urlparse(normalized)
        if parsed.path.startswith(settings.storage_url_prefix):
            return f"{settings.public_base_url}{parsed.path}"
        return normalized

    if normalized.startswith("/"):
        path = normalized
    else:
        path = f"{settings.storage_url_prefix}/{normalized.lstrip('/')}"

    return f"{settings.public_base_url}{path}"


def image_record_to_read(record: object) -> ImageRecordRead:
    payload = ImageRecordRead.model_validate(record)
    return payload.model_copy(update={"url_path": build_public_file_url(payload.url_path)})
