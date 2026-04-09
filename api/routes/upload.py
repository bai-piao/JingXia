from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from models.image import ImageRecord
from schemas.image import ImageRecordRead, image_record_to_read
from services.ai_service import process_image
from services.storage_service import save_upload_file

router = APIRouter(tags=["upload"])


@router.post(
    "/upload",
    response_model=ImageRecordRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ImageRecordRead:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a filename.",
        )

    try:
        stored_file = await save_upload_file(file)
        ai_result = await process_image(stored_file.absolute_path)

        image_record = ImageRecord(
            filename=stored_file.original_filename,
            local_path=stored_file.local_path,
            url_path=stored_file.url_path,
            ocr_text=ai_result["ocr_text"],
            tags=ai_result["tags"],
        )
        session.add(image_record)
        await session.commit()
        await session.refresh(image_record)
    finally:
        await file.close()

    return image_record_to_read(image_record)
