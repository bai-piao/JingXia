from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
from pathlib import Path
import re
from time import monotonic
from typing import Any, TypedDict

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_SEARCH_EXPANSION_CACHE_TTL_SECONDS = 300.0
_SEARCH_EXPANSION_CACHE: dict[str, tuple[float, list[str]]] = {}

_SYSTEM_PROMPT = (
    "你是一个认真工作的图片理解与 OCR 提取引擎。"
    "你必须先分析图片内容，再输出结果。"
    "你必须严格输出 JSON，不允许输出解释、前后缀、Markdown 或代码块。"
    '输出必须包含两个字段：{"tags": ["标签1", "标签2"], "ocr_text": "识别出的文字"}。'
    "tags 必须是字符串数组；ocr_text 必须是字符串。"
    "普通语义标签默认优先使用中文短标签，不要只输出英文。"
    "除非是通用安全分类或行业固定术语，否则请优先返回中文，例如：飞机、航班、食品、零食、巧克力、企业、公共交通、文档。"
    "如果你使用了英文分类标签，也应该同时给出对应中文标签。"
    "除非图片完全空白、纯色、损坏或无法辨认，否则 tags 不允许为空。"
    "即使你不完全确定，也要基于画面主体、场景、物体、颜色、文档类型给出 3 到 8 个最可能的标签。"
    "如果图片包含成人内容、裸露、内衣、泳装、性暗示、性行为、情色插画或其他 NSFW 要素，必须明确在 tags 中标记出来。"
    "对 NSFW 内容优先使用这些稳定标签：nsfw、suggestive、nudity、lingerie、swimwear、explicit、adult-content、情色、裸露、内衣。"
    "如果图片是动漫、插画、CG 或真人照片，也要在 tags 中注明，例如：anime、illustration、photo。"
    "OCR 必须尽量提取可见文字；只有在确实没有任何可读文字时，ocr_text 才允许为空字符串。"
    "不要输出空数组来回避分析任务，不要照抄示例结构。"
)

_RETRY_SYSTEM_PROMPT = (
    "上一次结果为空，这是不合格的。"
    "重新严格分析图片。"
    "只要图片里存在任何主体、场景、物体、文档、界面、器物或文字，就必须输出非空 tags。"
    "如果图片不是纯空白或彻底损坏，至少输出 3 个标签。"
    "普通语义标签优先输出中文，不要只给英文标签。"
    "如果存在成人内容、裸露、性暗示、内衣、泳装、情色或 NSFW 元素，必须把这类标签直接写进 tags。"
    "OCR 继续尽量转录所有可见文字。"
    "最终仍然只能输出 JSON，格式为 "
    '{"tags": ["标签1", "标签2", "标签3"], "ocr_text": "识别出的文字"}。'
)

_NSFW_PROMPT = (
    "你是一个图像安全标签分类器。"
    "你的任务是只判断图片中是否存在成人内容、擦边内容、裸露或身体敏感部位强调。"
    "请重点检查：胸部、乳沟、臀部、屁股、内衣、泳装、比基尼、透视衣物、局部特写、裸露程度、性暗示姿势。"
    "如果存在这些特征，必须把对应标签写入 tags。"
    "标签只从下面集合中选择："
    "nsfw, suggestive, nudity, explicit, lingerie, swimwear, breasts, cleavage, buttocks, hips, thighs, nipples, anime, illustration, photo。"
    "如果图片不包含这些成人或擦边要素，则返回空数组。"
    '只输出 JSON，格式必须是 {"tags": ["tag1", "tag2"]}。'
)

_TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "nsfw": ("nsfw", "adult-content", "成人内容", "十八禁", "r18"),
    "suggestive": ("suggestive", "性感", "擦边", "性暗示"),
    "nudity": ("nudity", "nude", "裸体", "裸露", "全裸"),
    "lingerie": ("lingerie", "内衣", "胸衣", "bra", "panties"),
    "swimwear": ("swimwear", "泳装", "比基尼", "泳衣", "bikini"),
    "explicit": ("explicit", "性交", "性行为", "露点", "porn", "色情", "情色"),
    "breasts": ("breasts", "breast", "胸部", "乳房", "胸", "巨乳"),
    "cleavage": ("cleavage", "乳沟", "胸沟"),
    "buttocks": ("buttocks", "臀部", "屁股", "臀", "ass"),
    "hips": ("hips", "胯部", "臀胯", "hip"),
    "thighs": ("thighs", "大腿", "腿部"),
    "nipples": ("nipples", "乳头"),
    "anime": ("anime", "动漫", "二次元"),
    "illustration": ("illustration", "插画", "绘画", "cg"),
    "photo": ("photo", "照片", "写真", "real-person", "真人"),
}

_CANONICAL_TAG_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "airplane": ("飞机",),
    "flight": ("航班",),
    "airport": ("机场",),
    "food": ("食品",),
    "snack": ("零食",),
    "chocolate": ("巧克力",),
    "company": ("企业",),
    "business": ("企业",),
    "public transport": ("公共交通", "公交"),
    "bus": ("公交", "公共交通"),
    "document": ("文档",),
    "invoice": ("发票",),
    "receipt": ("收据",),
    "phone": ("手机",),
    "smartphone": ("手机",),
    "train": ("火车", "列车"),
    "car": ("汽车",),
    "ship": ("船", "轮船"),
    "boat": ("船",),
    "anime": ("动漫",),
    "illustration": ("插画",),
    "photo": ("照片",),
    "nsfw": ("成人内容",),
    "adult-content": ("成人内容",),
    "suggestive": ("擦边", "性暗示"),
    "nudity": ("裸露",),
    "lingerie": ("内衣",),
    "swimwear": ("泳装",),
    "explicit": ("情色",),
    "breasts": ("胸部", "乳房"),
    "cleavage": ("乳沟",),
    "buttocks": ("臀部", "屁股"),
    "hips": ("胯部",),
    "thighs": ("大腿",),
    "nipples": ("乳头",),
}


class AIProcessResult(TypedDict):
    tags: list[str]
    ocr_text: str


class AISearchExpansionResult(TypedDict):
    terms: list[str]


class AITagListResult(TypedDict):
    tags: list[str]


def _empty_result() -> AIProcessResult:
    return {"tags": [], "ocr_text": ""}


def _normalize_result(payload: dict[str, Any]) -> AIProcessResult:
    raw_tags = payload.get("tags")
    tags = (
        [str(item).strip() for item in raw_tags if str(item).strip()]
        if isinstance(raw_tags, list)
        else []
    )
    tags = _normalize_tags(tags)

    raw_ocr_text = payload.get("ocr_text")
    ocr_text = str(raw_ocr_text).strip() if raw_ocr_text is not None else ""
    return {"tags": tags, "ocr_text": ocr_text}


def _normalize_tags(raw_tags: list[str]) -> list[str]:
    normalized_tags: list[str] = []
    seen: set[str] = set()

    def add_tag(tag: str) -> None:
        clean_tag = re.sub(r"\s+", " ", tag.strip())
        if len(clean_tag) < 2:
            return

        dedupe_key = clean_tag.lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        normalized_tags.append(clean_tag)

    lower_tags = [tag.lower() for tag in raw_tags]

    for tag in raw_tags:
        add_tag(tag)

    for canonical_tag, aliases in _TAG_ALIASES.items():
        if any(alias.lower() in tag for alias in aliases for tag in lower_tags):
            add_tag(canonical_tag)
            for expanded_tag in _CANONICAL_TAG_EXPANSIONS.get(canonical_tag, ()):
                add_tag(expanded_tag)

    # 对常见英文标签补中文别名，降低中文搜索丢失概率。
    for canonical_tag, expanded_tags in _CANONICAL_TAG_EXPANSIONS.items():
        if any(canonical_tag in tag for tag in lower_tags):
            for expanded_tag in expanded_tags:
                add_tag(expanded_tag)

    # 对成人内容统一补顶层标签，提升后续检索稳定性。
    nsfw_related = {"suggestive", "nudity", "lingerie", "swimwear", "explicit", "adult-content", "成人内容", "裸露", "情色", "内衣", "泳装"}
    if any(tag.lower() in {item.lower() for item in nsfw_related} for tag in normalized_tags):
        add_tag("nsfw")
        add_tag("成人内容")

    return normalized_tags


def _is_effectively_empty(result: AIProcessResult) -> bool:
    return not result["tags"] and not result["ocr_text"]


def _image_to_data_uri(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    with image_path.open("rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _extract_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("AI response does not contain any choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise TypeError("AI response choice is not a dict")

    message = first_choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_fragments = [
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return "\n".join(fragment for fragment in text_fragments if fragment)

    text = first_choice.get("text")
    if isinstance(text, str):
        return text.strip()

    raise ValueError("Unable to extract textual content from AI response")


def _strip_json_fence(raw_text: str) -> str:
    candidate = raw_text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?", "", candidate).strip()
        candidate = re.sub(r"```$", "", candidate).strip()
    return candidate


def _extract_first_json_object(raw_text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()

    for match in re.finditer(r"\{", raw_text):
        start = match.start()
        try:
            parsed, _ = decoder.raw_decode(raw_text[start:])
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict):
            return parsed

    raise json.JSONDecodeError("No valid JSON object found", raw_text, 0)


def _extract_first_json_value(raw_text: str) -> Any:
    decoder = json.JSONDecoder()

    for match in re.finditer(r"[\{\[]", raw_text):
        start = match.start()
        try:
            parsed, _ = decoder.raw_decode(raw_text[start:])
        except json.JSONDecodeError:
            continue
        return parsed

    raise json.JSONDecodeError("No valid JSON value found", raw_text, 0)


def _parse_json_result(raw_text: str) -> AIProcessResult:
    candidate = _strip_json_fence(raw_text)

    try:
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise TypeError("Parsed payload is not a JSON object")
        return _normalize_result(parsed)
    except (json.JSONDecodeError, TypeError):
        parsed = _extract_first_json_object(candidate)
        return _normalize_result(parsed)


def _parse_search_expansion_result(raw_text: str) -> AISearchExpansionResult:
    candidate = _strip_json_fence(raw_text)

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = _extract_first_json_value(candidate)

    raw_terms: Any
    if isinstance(parsed, dict):
        raw_terms = (
            parsed.get("terms")
            or parsed.get("keywords")
            or parsed.get("related_terms")
            or parsed.get("queries")
            or parsed.get("synonyms")
        )
    elif isinstance(parsed, list):
        raw_terms = parsed
    else:
        raise TypeError("Search expansion payload is not a JSON object or array")

    if not isinstance(raw_terms, list):
        raise TypeError("Search expansion payload does not contain a term list")

    normalized_terms: list[str] = []
    seen: set[str] = set()
    for item in raw_terms:
        term = str(item).strip()
        normalized_term = re.sub(r"\s+", " ", term)
        if len(normalized_term) < 2:
            continue
        dedupe_key = normalized_term.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_terms.append(normalized_term)
        if len(normalized_terms) >= 10:
            break

    return {"terms": normalized_terms}


def _parse_tag_list_result(raw_text: str) -> AITagListResult:
    candidate = _strip_json_fence(raw_text)

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = _extract_first_json_value(candidate)

    raw_tags: Any
    if isinstance(parsed, dict):
        raw_tags = parsed.get("tags")
    elif isinstance(parsed, list):
        raw_tags = parsed
    else:
        raise TypeError("Tag list payload is not a JSON object or array")

    if not isinstance(raw_tags, list):
        raise TypeError("Tag list payload does not contain a tag list")

    return {"tags": _normalize_tags([str(item).strip() for item in raw_tags if str(item).strip()])}


def _build_payload(image_data_uri: str, *, retry_on_empty: bool = False) -> dict[str, Any]:
    user_text = (
        "请分析这张图片。"
        "先识别主体、场景、物体、文档类型或界面元素，再提取图片中的可见文字。"
        "只返回 JSON。"
        "如果画面不是空白图，tags 不能留空。"
    )
    system_prompt = _RETRY_SYSTEM_PROMPT if retry_on_empty else _SYSTEM_PROMPT

    return {
        "model": settings.ai_model_name,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_text,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_uri,
                        },
                    },
                ],
            },
        ],
        "temperature": 0.0,
    }


def _build_nsfw_payload(image_data_uri: str) -> dict[str, Any]:
    return {
        "model": settings.ai_model_name,
        "messages": [
            {
                "role": "system",
                "content": _NSFW_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请判断图片是否包含成人或擦边内容，只返回 tags JSON。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_uri,
                        },
                    },
                ],
            },
        ],
        "temperature": 0.0,
    }


async def _request_ai_service(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = f"{settings.ai_api_base_url.rstrip('/')}/"
    timeout = httpx.Timeout(settings.ai_api_timeout)

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        response = await client.post(
            "chat/completions",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def expand_search_terms_via_ai(keyword: str) -> list[str]:
    normalized_keyword = re.sub(r"\s+", " ", keyword.strip())
    if len(normalized_keyword) < 2:
        return []

    cache_key = normalized_keyword.lower()
    now = monotonic()
    cached_entry = _SEARCH_EXPANSION_CACHE.get(cache_key)
    if cached_entry is not None:
        expires_at, cached_terms = cached_entry
        if expires_at > now:
            logger.info(
                "AI search expansion cache hit for %s: %s",
                normalized_keyword,
                cached_terms,
            )
            return cached_terms
        _SEARCH_EXPANSION_CACHE.pop(cache_key, None)

    payload = {
        "model": settings.ai_model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个图片知识库搜索词扩展助手。"
                    "你需要把用户输入的检索词扩展成更容易命中图片标签和 OCR 的相关搜索词。"
                    "可以输出近义词、简称、别名、上位词、下位词、常见英文词。"
                    "只输出 JSON，不允许输出解释。"
                    '格式必须是 {"terms": ["词1", "词2", "词3"]}。'
                    "terms 数量控制在 4 到 8 个。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请扩展这个图片检索词：{normalized_keyword}。"
                    "只返回 JSON。"
                ),
            },
        ],
        "temperature": 0.2,
    }

    try:
        response_payload = await _request_ai_service(payload)
        raw_content = _extract_content(response_payload)
        logger.info(
            "AI search expansion raw response for %s: %s",
            normalized_keyword,
            raw_content[:1200],
        )
        result = _parse_search_expansion_result(raw_content)
        terms = result["terms"]
        _SEARCH_EXPANSION_CACHE[cache_key] = (
            now + _SEARCH_EXPANSION_CACHE_TTL_SECONDS,
            terms,
        )
        logger.info(
            "AI search expansion terms for %s: %s",
            normalized_keyword,
            terms,
        )
        return terms
    except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning(
            "AI search expansion failed for keyword: %s",
            normalized_keyword,
            exc_info=True,
        )
        return []


async def extract_safety_tags_via_ai(image_data_uri: str) -> list[str]:
    payload = _build_nsfw_payload(image_data_uri)

    try:
        response_payload = await _request_ai_service(payload)
        raw_content = _extract_content(response_payload)
        logger.info("AI safety raw response: %s", raw_content[:1200])
        result = _parse_tag_list_result(raw_content)
        logger.info("AI safety tags: %s", result["tags"])
        return result["tags"]
    except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("AI safety tag extraction failed.", exc_info=True)
        return []


async def process_image(image_path: str | Path) -> AIProcessResult:
    normalized_path = Path(image_path).expanduser().resolve()
    if not normalized_path.is_file():
        logger.error("Image file not found for AI processing: %s", normalized_path)
        return _empty_result()

    try:
        image_data_uri = await asyncio.to_thread(_image_to_data_uri, normalized_path)
        payload = _build_payload(image_data_uri)

        response_payload = await _request_ai_service(payload)
        raw_content = _extract_content(response_payload)
        logger.info("AI raw response for %s: %s", normalized_path.name, raw_content[:1200])
        try:
            result = _parse_json_result(raw_content)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "AI returned non-parseable content for %s, retrying with a stricter prompt.",
                normalized_path,
                exc_info=True,
            )
            retry_payload = _build_payload(image_data_uri, retry_on_empty=True)
            retry_response_payload = await _request_ai_service(retry_payload)
            retry_raw_content = _extract_content(retry_response_payload)
            logger.info(
                "AI retry raw response for %s: %s",
                normalized_path.name,
                retry_raw_content[:1200],
            )
            return _parse_json_result(retry_raw_content)

        if _is_effectively_empty(result):
            logger.warning(
                "AI returned an empty result for %s, retrying with a stricter prompt.",
                normalized_path,
            )
            retry_payload = _build_payload(image_data_uri, retry_on_empty=True)
            retry_response_payload = await _request_ai_service(retry_payload)
            retry_raw_content = _extract_content(retry_response_payload)
            logger.info(
                "AI retry raw response for %s: %s",
                normalized_path.name,
                retry_raw_content[:1200],
            )
            retry_result = _parse_json_result(retry_raw_content)
            result = retry_result

        safety_tags = await extract_safety_tags_via_ai(image_data_uri)
        if safety_tags:
            result["tags"] = _normalize_tags([*(result["tags"] or []), *safety_tags])

        return result
    except httpx.TimeoutException:
        logger.error(
            "AI service request timed out after %ss for image: %s",
            settings.ai_api_timeout,
            image_path,
            exc_info=True,
        )
        return _empty_result()
    except httpx.ConnectError:
        logger.error(
            "AI service connection failed for image: %s, base_url=%s",
            image_path,
            settings.ai_api_base_url,
            exc_info=True,
        )
        return _empty_result()
    except httpx.HTTPStatusError:
        logger.error(
            "AI service returned non-success status for image: %s",
            image_path,
            exc_info=True,
        )
        return _empty_result()
    except httpx.RequestError:
        logger.error(
            "AI service request failed for image: %s",
            image_path,
            exc_info=True,
        )
        return _empty_result()
    except json.JSONDecodeError:
        logger.error(
            "Failed to decode AI JSON output for image: %s",
            image_path,
            exc_info=True,
        )
        return _empty_result()
    except (OSError, TypeError, ValueError):
        logger.error(
            "AI processing pipeline failed for image: %s",
            image_path,
            exc_info=True,
        )
        return _empty_result()
    except Exception:
        logger.error(
            "Unexpected AI processing failure for image: %s",
            image_path,
            exc_info=True,
        )
        return _empty_result()
