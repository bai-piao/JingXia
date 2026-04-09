from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import get_session
from models.image import ImageRecord
from schemas.image import ImageListRead, ImageRecordRead, image_record_to_read
from services.ai_service import expand_search_terms_via_ai
from fastapi import HTTPException, status

router = APIRouter(prefix="/images", tags=["images"])

_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("飞机", "航班", "客机", "airplane", "plane", "aircraft", "flight", "jet"),
    ("火车", "列车", "train", "rail", "railway"),
    ("汽车", "车", "轿车", "car", "auto", "automobile", "vehicle"),
    ("公交", "公交车", "公共交通", "巴士", "公车", "bus", "transit", "public transport"),
    ("地铁", "轨道交通", "metro", "subway", "underground"),
    ("nsfw", "adult-content", "成人内容", "色情", "情色", "十八禁", "r18"),
    ("裸露", "裸体", "全裸", "nudity", "nude"),
    ("内衣", "lingerie", "bra", "panties", "胸衣"),
    ("泳装", "泳衣", "比基尼", "swimwear", "bikini"),
    ("性感", "擦边", "性暗示", "suggestive", "provocative"),
    ("胸部", "乳房", "胸", "breasts", "breast"),
    ("乳沟", "cleavage", "胸沟"),
    ("臀部", "屁股", "臀", "buttocks", "ass"),
    ("胯部", "hips", "hip"),
    ("大腿", "thighs", "thigh"),
    ("乳头", "nipples", "nipple"),
    ("手机", "电话", "smartphone", "phone", "mobile"),
    ("发票", "票据", "收据", "invoice", "receipt", "bill"),
    ("文档", "文件", "document", "doc", "paper", "sheet"),
    ("船", "轮船", "船只", "ship", "boat", "vessel"),
)


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _tokenize_text(value: str | None) -> list[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return []
    return re.findall(r"[a-z0-9_+-]+|[\u4e00-\u9fff]{1,8}", normalized)


def _contains_or_overlaps(term: str, candidate: str) -> bool:
    return term in candidate or candidate in term


def _is_subsequence(term: str, candidate: str) -> bool:
    if not term or not candidate:
        return False

    term_index = 0
    for char in candidate:
        if term_index < len(term) and char == term[term_index]:
            term_index += 1
        if term_index == len(term):
            return True
    return False


def _expand_search_terms(keyword: str) -> set[str]:
    normalized = _normalize_text(keyword)
    if not normalized:
        return set()

    terms = {normalized, normalized.replace(" ", "")}
    terms.update(token for token in _tokenize_text(normalized) if len(token) >= 2)

    for group in _SYNONYM_GROUPS:
        group_set = set(group)
        if any(
            _contains_or_overlaps(term, candidate)
            for term in terms
            for candidate in group_set
        ):
            terms.update(group_set)

    return {term for term in terms if term}


def _build_keyword_filter(keyword: str | None):
    normalized_keyword = keyword.strip() if keyword else ""
    if not normalized_keyword:
        return None

    like_pattern = f"%{normalized_keyword}%"
    tag_values = func.json_each(ImageRecord.tags).table_valued("value").alias("tag_values")
    return or_(
        ImageRecord.ocr_text.like(like_pattern),
        exists(
            select(1)
            .select_from(tag_values)
            .where(tag_values.c.value.like(like_pattern))
        ),
    )


def _score_image(record: ImageRecord, search_terms: set[str]) -> int:
    tags = [_normalize_text(tag) for tag in (record.tags or []) if _normalize_text(tag)]
    ocr_text = _normalize_text(record.ocr_text)
    filename = _normalize_text(record.filename)

    searchable_text = " ".join(part for part in [ocr_text, filename, *tags] if part)
    searchable_tokens = set(tags)
    for tag in tags:
        searchable_tokens.update(_tokenize_text(tag))
    searchable_tokens.update(_tokenize_text(ocr_text))
    searchable_tokens.update(_tokenize_text(filename))

    score = 0
    for term in search_terms:
        if not term:
            continue

        if any(term in tag or tag in term for tag in tags):
            score += 120
            continue

        if term in searchable_text:
            score += 75
            continue

        if any(
            len(term) >= 2 and len(token) > len(term) and _is_subsequence(term, token)
            for token in searchable_tokens
        ):
            score += 52
            continue

        best_ratio = 0.0
        for token in searchable_tokens:
            if len(token) < 2:
                continue
            ratio = SequenceMatcher(None, term, token).ratio()
            if ratio > best_ratio:
                best_ratio = ratio

        if best_ratio >= 0.84:
            score += int(best_ratio * 60)
        elif best_ratio >= 0.72:
            score += int(best_ratio * 35)

    return score


@router.get("", response_model=ImageListRead)
async def list_images(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> ImageListRead:
    offset = (page - 1) * page_size

    normalized_keyword = keyword.strip() if keyword else ""
    if normalized_keyword:
        search_terms = _expand_search_terms(normalized_keyword)
        debug_source = "lexical"
        items_result = await session.execute(
            select(ImageRecord).order_by(ImageRecord.created_at.desc())
        )
        all_records = items_result.scalars().all()

        def rank_records(terms: set[str]) -> list[tuple[ImageRecord, int]]:
            ranked: list[tuple[ImageRecord, int]] = []
            for record in all_records:
                score = _score_image(record, terms)
                if score > 0:
                    ranked.append((record, score))
            ranked.sort(key=lambda item: item[1], reverse=True)
            return ranked

        ranked_records = rank_records(search_terms)
        if not ranked_records:
            ai_terms = await expand_search_terms_via_ai(normalized_keyword)
            if ai_terms:
                search_terms.update(_expand_search_terms(" ".join(ai_terms)))
                ranked_records = rank_records(search_terms)
                debug_source = "ai_fallback"

        total = len(ranked_records)
        page_records = [record for record, _ in ranked_records[offset : offset + page_size]]
        items = [image_record_to_read(record) for record in page_records]

        return ImageListRead(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            debug_terms=sorted(search_terms),
            debug_source=debug_source,
        )

    count_stmt = select(func.count()).select_from(ImageRecord)
    items_stmt = (
        select(ImageRecord)
        .order_by(ImageRecord.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    total_result = await session.execute(count_stmt)
    items_result = await session.execute(items_stmt)

    total = int(total_result.scalar_one() or 0)
    items = [image_record_to_read(record) for record in items_result.scalars().all()]

    return ImageListRead(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        debug_terms=None,
        debug_source=None,
    )


@router.delete("/{image_id}")
async def delete_image(
    image_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    image_record = await session.get(ImageRecord, image_id)
    if image_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    image_path = settings.storage_root / Path(image_record.local_path)
    image_path.unlink(missing_ok=True)

    await session.delete(image_record)
    await session.commit()

    return {"status": "success", "message": "Image deleted"}
