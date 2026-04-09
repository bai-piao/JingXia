from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Text
from sqlmodel import Field, SQLModel


class ImageRecord(SQLModel, table=True):
    __tablename__ = "image_records"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    filename: str = Field(nullable=False, max_length=255)
    local_path: str = Field(nullable=False, index=True, max_length=512)
    url_path: str = Field(nullable=False, max_length=512)
    ocr_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    tags: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
