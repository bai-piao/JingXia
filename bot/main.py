from __future__ import annotations

import io
import logging
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import urljoin

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    PhotoSize,
)

from core.env import load_project_env

load_project_env()

logger = logging.getLogger(__name__)

_UPLOAD_TIMEOUT_SECONDS = 180.0
_OCR_PREVIEW_LIMIT = 1500


@dataclass(frozen=True, slots=True)
class BotSettings:
    telegram_token: str
    jingxia_api_base: str

    def build_file_url(self, url_path: str) -> str:
        if url_path.startswith(("http://", "https://")):
            return url_path

        normalized_path = url_path if url_path.startswith("/") else f"/{url_path}"
        return urljoin(f"{self.jingxia_api_base.rstrip('/')}/", normalized_path)


class JingXiaCoreClient:
    def __init__(self, api_base: str, timeout_seconds: float = _UPLOAD_TIMEOUT_SECONDS) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"{api_base.rstrip('/')}/",
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def __aenter__(self) -> JingXiaCoreClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def upload_image(
        self,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        response = await self._client.post(
            "upload",
            files={"file": (filename, content, content_type)},
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("jingxia-core upload response is not a JSON object")
        return payload

    async def search_images(self, keyword: str, *, page_size: int = 3) -> dict[str, Any]:
        response = await self._client.get(
            "images",
            params={
                "keyword": keyword,
                "page": 1,
                "page_size": page_size,
            },
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("jingxia-core images response is not a JSON object")
        return payload

    async def list_images(self, *, page: int = 1, page_size: int = 5) -> dict[str, Any]:
        response = await self._client.get(
            "images",
            params={
                "page": page,
                "page_size": page_size,
            },
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("jingxia-core images response is not a JSON object")
        return payload

    async def download_image(self, image_url: str) -> bytes:
        response = await self._client.get(image_url)
        response.raise_for_status()
        return response.content

    async def delete_image(self, image_id: str) -> dict[str, Any]:
        response = await self._client.delete(f"images/{image_id}")
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("jingxia-core delete response is not a JSON object")
        return payload


def load_settings() -> BotSettings:
    telegram_token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not telegram_token:
        raise RuntimeError("TG_BOT_TOKEN is required.")

    return BotSettings(
        telegram_token=telegram_token,
        jingxia_api_base=os.getenv("JINGXIA_API_BASE", "http://127.0.0.1:8000/api/v1").strip(),
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _resolve_media(message: Message) -> tuple[PhotoSize | Document, str, str]:
    if message.photo:
        photo = message.photo[-1]
        return photo, f"telegram_{photo.file_unique_id}.jpg", "image/jpeg"

    document = message.document
    if document is None:
        raise ValueError("Message does not contain a photo or document.")

    filename = document.file_name or f"telegram_{document.file_unique_id}"
    mime_type = document.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise ValueError("Only image documents are supported.")

    return document, filename, mime_type


def _format_result_message(result: dict[str, Any], settings: BotSettings) -> str:
    url_path = str(result.get("url_path", "")).strip()
    file_url = settings.build_file_url(url_path) if url_path else ""

    tags = result.get("tags")
    tags_text = ", ".join(str(tag).strip() for tag in tags or [] if str(tag).strip()) or "无"

    ocr_text = str(result.get("ocr_text") or "").strip() or "无"
    ocr_text = _truncate(ocr_text, _OCR_PREVIEW_LIMIT)

    lines = [
        "<b>归档完成</b>",
        f"直链：<a href=\"{escape(file_url, quote=True)}\">{escape(file_url)}</a>" if file_url else "直链：无",
        f"Tags：{escape(tags_text)}",
        f"OCR：\n{escape(ocr_text)}",
    ]
    return "\n".join(lines)


async def _edit_status_message(status_message: Message, text: str) -> None:
    try:
        await status_message.edit_text(text)
    except TelegramBadRequest:
        logger.exception("Failed to edit status message, falling back to reply.")
        await status_message.reply(text)


async def _delete_message_quietly(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        logger.exception("Failed to delete placeholder status message.")


def _build_search_caption(item: dict[str, Any]) -> str:
    tags = item.get("tags")
    tags_text = ", ".join(
        str(tag).strip() for tag in tags or [] if str(tag).strip()
    ) or "无"
    ocr_text = _truncate(str(item.get("ocr_text") or "").strip() or "无", 700)

    return "\n".join(
        [
            "<b>检索命中</b>",
            f"Tags：{escape(tags_text)}",
            f"OCR：{escape(ocr_text)}",
        ]
    )


def _build_list_caption(item: dict[str, Any]) -> str:
    tags = item.get("tags")
    tags_text = ", ".join(
        str(tag).strip() for tag in tags or [] if str(tag).strip()
    ) or "无"
    ocr_text = _truncate(str(item.get("ocr_text") or "").strip() or "无", 220)

    created_at_raw = str(item.get("created_at") or "").strip()
    created_at_text = created_at_raw or "未知"
    if created_at_raw:
        try:
            created_at_text = datetime.fromisoformat(
                created_at_raw.replace("Z", "+00:00")
            ).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            created_at_text = created_at_raw

    return "\n".join(
        [
            "<b>最近归档</b>",
            f"Tags：{escape(tags_text)}",
            f"OCR：{escape(ocr_text)}",
            f"归档时间：{escape(created_at_text)}",
        ]
    )


def _build_gallery_keyboard(
    *,
    image_id: str,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    previous_button = InlineKeyboardButton(
        text="⬅️ 上一张" if current_page > 1 else " ",
        callback_data=f"gallery_page_{current_page - 1}" if current_page > 1 else "ignore",
    )
    progress_button = InlineKeyboardButton(
        text=f"📄 {current_page} / {total_pages}",
        callback_data="ignore",
    )
    next_button = InlineKeyboardButton(
        text="下一张 ➡️" if current_page < total_pages else " ",
        callback_data=f"gallery_page_{current_page + 1}" if current_page < total_pages else "ignore",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑️ 删除",
                    callback_data=f"gallery_del_{image_id}_{current_page}",
                )
            ],
            [previous_button, progress_button, next_button],
        ]
    )


def _build_search_debug_message(
    *,
    keyword: str,
    total: int,
    debug_source: str | None,
    debug_terms: Any,
) -> str:
    source_label = "词法检索"
    if debug_source == "ai_fallback":
        source_label = "AI 联想检索"

    normalized_terms = []
    if isinstance(debug_terms, list):
        normalized_terms = [
            str(term).strip() for term in debug_terms if str(term).strip()
        ]

    expanded_terms = [term for term in normalized_terms if term != keyword]
    expanded_text = "、".join(expanded_terms[:10]) if expanded_terms else "无"

    return "\n".join(
        [
            f"🔎 检索完成：{escape(keyword)}",
            f"命中：{total} 张",
            f"来源：{escape(source_label)}",
            f"扩词：{escape(expanded_text)}",
        ]
    )


async def _call_ai_text_completion(system_prompt: str, user_prompt: str) -> str:
    ai_api_base_url = os.getenv("AI_API_BASE_URL", "http://127.0.0.1:8081/v1").strip().rstrip("/")
    ai_model_name = os.getenv("AI_MODEL_NAME", "qwen-vl").strip() or "qwen-vl"

    async with httpx.AsyncClient(
        base_url=f"{ai_api_base_url}/",
        timeout=httpx.Timeout(30.0),
    ) as client:
        response = await client.post(
            "chat/completions",
            json={
                "model": ai_model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            },
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise TypeError("AI response is not a JSON object")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("AI response does not contain choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise TypeError("AI choice payload is invalid")

    message_payload = first_choice.get("message")
    if isinstance(message_payload, dict):
        content = message_payload.get("content")
        if isinstance(content, str):
            return content.strip()

    text = first_choice.get("text")
    if isinstance(text, str):
        return text.strip()

    raise ValueError("Unable to extract text from AI response")


async def _build_gallery_page(
    *,
    core_client: JingXiaCoreClient,
    settings: BotSettings,
    page: int,
) -> tuple[InputMediaPhoto, InlineKeyboardMarkup, int, int] | None:
    requested_page = max(1, page)
    payload = await core_client.list_images(page=requested_page, page_size=1)

    total = int(payload.get("total", 0) or 0)
    items = payload.get("items")
    if total <= 0:
        return None

    total_pages = total
    current_page = min(requested_page, total_pages)

    if current_page != requested_page:
        payload = await core_client.list_images(page=current_page, page_size=1)
        items = payload.get("items")

    if not isinstance(items, list) or not items:
        return None

    item = items[0]
    if not isinstance(item, dict):
        return None

    image_id = str(item.get("id") or "").strip()
    url_path = str(item.get("url_path") or "").strip()
    if not image_id or not url_path:
        return None

    image_url = settings.build_file_url(url_path)
    image_bytes = await core_client.download_image(image_url)
    filename = str(item.get("filename") or "jingxia-gallery.jpg")
    media = InputMediaPhoto(
        media=BufferedInputFile(image_bytes, filename=filename),
        caption=_build_list_caption(item),
        parse_mode=ParseMode.HTML,
    )
    keyboard = _build_gallery_keyboard(
        image_id=image_id,
        current_page=current_page,
        total_pages=total_pages,
    )
    return media, keyboard, current_page, total_pages


def create_router(core_client: JingXiaCoreClient, settings: BotSettings) -> Router:
    router = Router(name="jingxia_bot")

    @router.message(F.photo)
    @router.message(F.document)
    async def archive_image(message: Message, bot: Bot) -> None:
        status_message = await message.reply("⏳ 镜匣大脑正在提取图像特征，请稍候...")

        try:
            media, filename, mime_type = _resolve_media(message)
            buffer = io.BytesIO()
            await bot.download(media, destination=buffer, timeout=60)
            payload = await core_client.upload_image(
                filename=filename,
                content=buffer.getvalue(),
                content_type=mime_type,
            )
            await _edit_status_message(
                status_message,
                _format_result_message(payload, settings),
            )
        except ValueError:
            logger.exception("Unsupported Telegram media payload.")
            await _edit_status_message(status_message, "归档失败：仅支持图片或图片文件。")
        except httpx.TimeoutException:
            logger.exception("Timed out while uploading image to jingxia-core.")
            await _edit_status_message(status_message, "归档失败：镜匣核心服务响应超时。")
        except httpx.HTTPStatusError:
            logger.exception("jingxia-core returned a non-success response.")
            await _edit_status_message(status_message, "归档失败：镜匣核心服务返回异常。")
        except httpx.RequestError:
            logger.exception("Failed to reach jingxia-core.")
            await _edit_status_message(status_message, "归档失败：无法连接镜匣核心服务。")
        except Exception:
            logger.exception("Unexpected error while archiving Telegram image.")
            await _edit_status_message(status_message, "归档失败：处理图片时发生未知错误。")

    @router.message(Command("list"))
    async def list_recent_images(message: Message) -> None:
        try:
            gallery = await _build_gallery_page(
                core_client=core_client,
                settings=settings,
                page=1,
            )
            if gallery is None:
                await message.reply("📭 匣子空空如也")
                return

            media, keyboard, _, _ = gallery
            await message.answer_photo(
                photo=media.media,
                caption=media.caption,
                parse_mode=media.parse_mode,
                reply_markup=keyboard,
            )
        except (httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException):
            logger.exception("Failed to load recent images from jingxia-core.")
            await message.reply("列表加载失败，请稍后重试。")
        except Exception:
            logger.exception("Unexpected error while opening gallery.")
            await message.reply("列表加载失败，请稍后重试。")

    @router.callback_query(F.data == "ignore")
    async def ignore_gallery_callback(callback_query: CallbackQuery) -> None:
        await callback_query.answer()

    @router.callback_query(F.data.startswith("gallery_page_"))
    async def paginate_gallery(callback_query: CallbackQuery) -> None:
        if callback_query.message is None or callback_query.data is None:
            await callback_query.answer("无效请求", show_alert=True)
            return

        try:
            target_page = int(callback_query.data.removeprefix("gallery_page_"))
            gallery = await _build_gallery_page(
                core_client=core_client,
                settings=settings,
                page=target_page,
            )
            if gallery is None:
                await callback_query.answer("📭 没有更多图片了", show_alert=False)
                return

            media, keyboard, _, _ = gallery
            await callback_query.message.edit_media(
                media=media,
                reply_markup=keyboard,
            )
            await callback_query.answer()
        except (ValueError, httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException):
            logger.exception("Failed to paginate gallery.")
            await callback_query.answer("翻页失败，请稍后重试。", show_alert=True)
        except Exception:
            logger.exception("Unexpected error while paginating gallery.")
            await callback_query.answer("翻页失败，请稍后重试。", show_alert=True)

    @router.callback_query(F.data.startswith("gallery_del_"))
    async def delete_image_from_gallery(callback_query: CallbackQuery) -> None:
        if callback_query.message is None or callback_query.data is None:
            await callback_query.answer("无效请求", show_alert=True)
            return

        try:
            payload = callback_query.data.removeprefix("gallery_del_")
            image_id, current_page_raw = payload.rsplit("_", 1)
            current_page = int(current_page_raw)

            await core_client.delete_image(image_id)

            gallery = await _build_gallery_page(
                core_client=core_client,
                settings=settings,
                page=current_page,
            )

            if gallery is None:
                await callback_query.message.delete()
                await callback_query.answer("已清空")
                return

            media, keyboard, _, _ = gallery
            await callback_query.message.edit_media(
                media=media,
                reply_markup=keyboard,
            )
            await callback_query.answer("已删除")
        except (ValueError, httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException):
            logger.exception("Failed to delete gallery image.")
            await callback_query.answer("删除失败，请稍后重试。", show_alert=True)
        except Exception:
            logger.exception("Unexpected error while deleting gallery image.")
            await callback_query.answer("删除失败，请稍后重试。", show_alert=True)

    @router.message(Command("ask"))
    async def ask_with_memory(message: Message) -> None:
        raw_text = (message.text or "").strip()
        command_parts = raw_text.split(maxsplit=1)
        question = command_parts[1].strip() if len(command_parts) > 1 else ""
        if not question:
            await message.reply("用法：/ask 你的问题")
            return

        status_message = await message.reply("🧠 正在思考并检索记忆...")

        try:
            keyword_text = await _call_ai_text_completion(
                "你是一个关键词提取器。请从用户的提问中提取出1到2个核心名词作为数据库搜索关键词。不要解释，只返回关键词，用空格隔开。",
                question,
            )
            keyword = " ".join(keyword_text.split()).strip() or question

            payload = await core_client.search_images(keyword, page_size=3)
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                await _edit_status_message(status_message, "📭 记忆中没有找到与此相关的信息。")
                return

            context_chunks: list[str] = []
            related_links: list[str] = []
            for index, item in enumerate(items[:3], start=1):
                if not isinstance(item, dict):
                    continue

                ocr_text = str(item.get("ocr_text") or "").strip()
                if ocr_text:
                    context_chunks.append(f"[背景资料 {index}]\n{ocr_text}")

                url_path = str(item.get("url_path") or "").strip()
                if url_path:
                    related_links.append(settings.build_file_url(url_path))

            if not context_chunks:
                await _edit_status_message(status_message, "📭 记忆中没有找到与此相关的信息。")
                return

            context = "\n\n".join(context_chunks)
            answer_text = await _call_ai_text_completion(
                "你是一个精准的知识库助手。请严格根据我提供的[背景资料]回答用户问题。如果资料中没有答案，请直接回答'资料中未包含此信息'，不要瞎编。",
                f"背景资料：\n{context}\n\n用户问题：{question}",
            )
            answer_body = escape(answer_text.strip() or "资料中未包含此信息")

            lines = [
                "<b>问答结果</b>",
                answer_body,
            ]

            if related_links:
                link_text = " | ".join(
                    f'<a href="{escape(link, quote=True)}">相关图片{index}</a>'
                    for index, link in enumerate(related_links[:3], start=1)
                )
                lines.extend(["", f"参考：{link_text}"])

            await _edit_status_message(status_message, "\n".join(lines))
        except httpx.TimeoutException:
            logger.exception("Timed out while performing /ask RAG flow.")
            await _edit_status_message(status_message, "问答失败：镜匣大脑思考超时。")
        except httpx.HTTPStatusError:
            logger.exception("AI or core service returned a non-success response during /ask.")
            await _edit_status_message(status_message, "问答失败：镜匣服务暂时不可用。")
        except httpx.RequestError:
            logger.exception("Failed to reach AI or core service during /ask.")
            await _edit_status_message(status_message, "问答失败：无法连接镜匣记忆服务。")
        except Exception:
            logger.exception("Unexpected error while handling /ask.")
            await _edit_status_message(status_message, "问答失败：处理问题时发生未知错误。")

    @router.message(F.text)
    async def search_images(message: Message) -> None:
        keyword = (message.text or "").strip()
        if not keyword:
            return

        status_message = await message.reply(f"🔍 正在镜匣中检索: {keyword}...")

        try:
            payload = await core_client.search_images(keyword, page_size=3)
            items = payload.get("items")
            total = int(payload.get("total", 0) or 0)
            debug_source = payload.get("debug_source")
            debug_terms = payload.get("debug_terms")
            if not isinstance(items, list) or not items or total == 0:
                await _edit_status_message(status_message, "📭 匣子空空如也，没有找到相关的图片。")
                return

            for item in items[:3]:
                if not isinstance(item, dict):
                    continue

                url_path = str(item.get("url_path") or "").strip()
                if not url_path:
                    continue

                image_url = settings.build_file_url(url_path)
                image_bytes = await core_client.download_image(image_url)
                filename = str(item.get("filename") or "jingxia-result.jpg")

                await message.answer_photo(
                    photo=BufferedInputFile(image_bytes, filename=filename),
                    caption=_build_search_caption(item),
                )

            await _edit_status_message(
                status_message,
                _build_search_debug_message(
                    keyword=keyword,
                    total=total,
                    debug_source=debug_source if isinstance(debug_source, str) else None,
                    debug_terms=debug_terms,
                ),
            )
        except httpx.TimeoutException:
            logger.exception("Timed out while searching jingxia-core.")
            await _edit_status_message(status_message, "检索失败：镜匣核心服务响应超时。")
        except httpx.HTTPStatusError:
            logger.exception("jingxia-core returned a non-success response while searching.")
            await _edit_status_message(status_message, "检索失败：镜匣核心服务返回异常。")
        except httpx.RequestError:
            logger.exception("Failed to reach jingxia-core while searching.")
            await _edit_status_message(status_message, "检索失败：无法连接镜匣核心服务。")
        except TelegramBadRequest:
            logger.exception("Telegram rejected the search result payload.")
            await _edit_status_message(status_message, "检索失败：Telegram 无法发送检索结果。")
        except Exception:
            logger.exception("Unexpected error while searching JingXia.")
            await _edit_status_message(status_message, "检索失败：处理检索结果时发生未知错误。")

    return router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    settings = load_settings()
    dispatcher = Dispatcher()

    async with Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        async with JingXiaCoreClient(settings.jingxia_api_base) as core_client:
            dispatcher.include_router(create_router(core_client, settings))
            await dispatcher.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
