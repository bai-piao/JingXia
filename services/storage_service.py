from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from fastapi import UploadFile

from core.config import settings


@dataclass(frozen=True, slots=True)
class StoredFile:
    original_filename: str
    local_path: str
    url_path: str
    absolute_path: Path


def _write_file(source: BinaryIO, destination: Path) -> None:
    source.seek(0)
    with destination.open("wb") as target:
        shutil.copyfileobj(source, target)


async def save_upload_file(upload_file: UploadFile) -> StoredFile:
    now = datetime.now()
    suffix = Path(upload_file.filename or "").suffix.lower()
    unique_name = f"{uuid4()}{suffix}"
    relative_path = Path(f"{now.year:04d}") / f"{now.month:02d}" / unique_name
    absolute_path = settings.storage_root / relative_path

    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_write_file, upload_file.file, absolute_path)

    local_path = relative_path.as_posix()
    url_path = f"{settings.public_base_url}{settings.storage_url_prefix}/{local_path}"
    return StoredFile(
        original_filename=upload_file.filename or unique_name,
        local_path=local_path,
        url_path=url_path,
        absolute_path=absolute_path,
    )
