"""aiogram 3 handlers for INFINITRIX SEARCH."""
from __future__ import annotations

import asyncio
import html
import io
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import ErrorEvent, InputMediaPhoto, LinkPreviewOptions, Message, PhotoSize
from aiogram.utils.chat_action import ChatActionSender

import core
from core import AppContext, User, UserFacingError
from search import SearchError, SearchResponse, format_response_html, upload_temp_image
from utils import pack_blocks, split_message

log = logging.getLogger("infinitrix.handlers")
router = Router(name="infinitrix")

MAX_PHOTO_BYTES = 8 * 1024 * 1024
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
TAG_RE = re.compile(r"<[^>]+>")

HELP_TEXT = """📖 دليل INFINITRIX SEARCH

💬 المحادثة
• اكتب أي رسالة في الخاص وسأجيبك (لدي ذاكرة خاصة بك).
• /ask سؤال — إجابة مدعومة ببحث مباشر في الإنترنت
• /autosearch on|off — تفعيل/إيقاف البحث التلقائي مع كل رسالة
• /clear — مسح ذاكرة محادثتك

🔎 البحث (SerpApi)
• /search كلمات — بحث الويب
• /images كلمات — صور Google
• /videos كلمات — فيديوهات
• /news كلمات — أخبار
• /reverse — بحث عكسي بالصورة: أرسل صورة مع التعليق /reverse
  أو ردّ على صورة بـ /reverse، أو /reverse رابط_صورة

ℹ️ أخرى
• /status — حالتك واستخدامك اليوم
• /help — هذه الرسالة"""

OWNER_HELP = """

👑 أوامر المالك
• /setprompt نص — تغيير البرومبت (أو ردّ على رسالة تحتوي البرومبت)
• /showprompt — عرض البرومبت الحالي
• /resetprompt — الرجوع للبرومبت الافتراضي"""


# ------------------------------------------------------------------ helpers
def to_user(message: Message) -> User:
    u = message.from_user
    if u is None:
        raise UserFacingError(None)
    return User(id=u.id, username=u.username, full_name=u.full_name or "")


async def _send_one(message: Message, chunk: str, html_mode: bool) -> None:
    for _ in range(3):
        try:
            if html_mode:
                await message.answer(chunk, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
            else:
                await message.answer(chunk, parse_mode=None, link_preview_options=NO_PREVIEW)
            return
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(exc.retry_after + 1, 30))
        except TelegramBadRequest as exc:
            if html_mode:  # malformed HTML → fall back to plain text
                html_mode = False
                chunk = html.unescape(TAG_RE.sub("", chunk))
                continue
            log.warning("Telegram rejected message: %s", exc)
            return
        except TelegramForbiddenError:
            return  # user blocked the bot / chat unavailable
        except TelegramAPIError as exc:
            log.warning("Telegram API error while sending: %s", exc)
            return


async def send_text(message: Message, text: str) -> None:
    """Send plain text of any length, split into Telegram-sized messages."""
    for chunk in split_message(text):
        await _send_one(message, chunk, html_mode=False)


async def send_html_blocks(message: Message, blocks: list[str]) -> None:
    for chunk in pack_blocks(blocks):
        await _send_one(message, chunk, html_mode=True)


def _is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


# -------------------------------------------------------------- basic commands
@router.message(CommandStart())
async def cmd_start(message: Message, ctx: AppContext) -> None:
    user = to_user(message)
    await ctx.db.touch_user(user.id, user.username, user.full_name)
    name = html.escape(user.full_name or "صديقي")
    await message.answer(
        f"أهلاً {name} 👋\n"
        "أنا <b>INFINITRIX SEARCH</b> — مساعد ذكي مباشر وإبداعي مع بحث حي في الإنترنت "
        "(ويب، صور، فيديو، أخبار، وبحث عكسي بالصورة).\n\n"
        "اكتب لي أي شيء لنبدأ، أو استخدم /help لرؤية كل الأوامر.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("help"))
async def cmd_help(message: Message, ctx: AppContext) -> None:
    user = to_user(message)
    text = HELP_TEXT + (OWNER_HELP if ctx.is_owner(user.id) else "")
    await send_text(message, text)


@router.message(Command("clear"))
async def cmd_clear(message: Message, ctx: AppContext) -> None:
    user = to_user(message)
    removed = await core.clear_memory(ctx, user)
    await send_text(message, f"🧹 تم مسح ذاكرة محادثتك ({removed} رسالة).")


@router.message(Command("status"))
async def cmd_status(message: Message, ctx: AppContext) -> None:
    user = to_user(message)
    await ctx.db.touch_user(user.id, user.username, user.full_name)
    await send_text(message, await core.build_status(ctx, user))


# ---------------------------------------------------------- owner: system prompt
@router.message(Command("setprompt"))
async def cmd_setprompt(message: Message, ctx: AppContext, command: CommandObject) -> None:
    user = to_user(message)
    text = (command.args or "").strip()
    if not text and message.reply_to_message:
        text = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    length = await core.set_prompt(ctx, user, text)
    await send_text(message, f"✅ تم حفظ البرومبت الجديد ({length} حرف). سيُستخدم في كل طلب، وسيبقى بعد إعادة التشغيل.")


@router.message(Command("showprompt"))
async def cmd_showprompt(message: Message, ctx: AppContext) -> None:
    user = to_user(message)
    prompt, custom = await core.show_prompt(ctx, user)
    header = "📝 البرومبت الحالي (مخصص):" if custom else "📝 البرومبت الحالي (الافتراضي):"
    await send_text(message, f"{header}\n\n{prompt}")


@router.message(Command("resetprompt"))
async def cmd_resetprompt(message: Message, ctx: AppContext) -> None:
    user = to_user(message)
    existed = await core.reset_prompt(ctx, user)
    await send_text(
        message,
        "♻️ تمت إعادة البرومبت الافتراضي." if existed else "ℹ️ لا يوجد برومبت مخصص، البرومبت الافتراضي مستخدم أصلاً.",
    )


# ------------------------------------------------------------------- AI chat
async def _run_chat(message: Message, ctx: AppContext, question: str, use_search: bool) -> None:
    user = to_user(message)
    async with ChatActionSender.typing(chat_id=message.chat.id, bot=message.bot):
        result = await core.chat(ctx, user, question, use_search=use_search)
    await send_text(message, result.text)
    if result.search_response and result.search_response.items:
        # Render only the URLs returned by SerpApi as clickable, titled links.
        await send_html_blocks(message, format_response_html(result.search_response))
    if result.notes:
        await send_text(message, "\n".join(result.notes))


@router.message(Command("ask"))
async def cmd_ask(message: Message, ctx: AppContext, command: CommandObject) -> None:
    question = (command.args or "").strip()
    if not question and message.reply_to_message:
        question = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not question:
        await send_text(message, "الاستخدام: /ask سؤالك\nمثال: /ask ما أحدث أخبار الذكاء الاصطناعي؟")
        return
    await _run_chat(message, ctx, question, use_search=True)


@router.message(Command("autosearch"))
async def cmd_autosearch(message: Message, ctx: AppContext, command: CommandObject) -> None:
    user = to_user(message)
    arg = (command.args or "").strip().lower()
    if arg in {"on", "1", "تشغيل", "نعم"}:
        await core.set_autosearch(ctx, user, True)
        await send_text(message, "✅ تم تفعيل البحث التلقائي: سأبحث في الإنترنت مع كل رسالة (يستهلك من حد البحث اليومي).")
    elif arg in {"off", "0", "ايقاف", "إيقاف", "لا"}:
        await core.set_autosearch(ctx, user, False)
        await send_text(message, "✅ تم إيقاف البحث التلقائي. استخدم /ask عندما تحتاج بحثاً.")
    else:
        state = "مفعّل" if await core.get_autosearch(ctx, user) else "متوقف"
        await send_text(message, f"البحث التلقائي حالياً: {state}\nالاستخدام: /autosearch on أو /autosearch off")


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, ctx: AppContext) -> None:
    if not _is_private(message):
        return  # in groups the bot only reacts to commands
    user = to_user(message)
    use_search = await core.get_autosearch(ctx, user)
    await _run_chat(message, ctx, message.text or "", use_search)


# ------------------------------------------------------------------- searches
async def _do_search(message: Message, ctx: AppContext, command: CommandObject, kind: str, usage: str) -> None:
    query = (command.args or "").strip()
    if not query and message.reply_to_message:
        query = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not query:
        await send_text(message, usage)
        return
    user = to_user(message)
    async with ChatActionSender.typing(chat_id=message.chat.id, bot=message.bot):
        resp = await core.run_search(ctx, user, kind, query)
    await _send_search_response(message, resp)


async def _send_search_response(message: Message, resp: SearchResponse) -> None:
    if resp.kind == "images" and resp.items:
        await _send_image_previews(message, resp)
    await send_html_blocks(message, format_response_html(resp))


async def _send_image_previews(message: Message, resp: SearchResponse) -> None:
    # Prefer original (full) URL over thumbnail. Google SafeSearch thumbnails are
    # often blurred for sensitive content even when the original is not.
    urls = [i.original or i.thumbnail for i in resp.items if (i.original or i.thumbnail)][:5]
    if not urls:
        return
    try:
        if len(urls) == 1:
            await message.answer_photo(urls[0])
        else:
            await message.answer_media_group([InputMediaPhoto(media=u) for u in urls])
    except TelegramRetryAfter as exc:
        log.warning("Rate limited while sending images (%ss)", exc.retry_after)
    except TelegramAPIError as exc:
        log.info("Could not send image previews, falling back to links only: %s", exc)


@router.message(Command("search"))
async def cmd_search(message: Message, ctx: AppContext, command: CommandObject) -> None:
    await _do_search(message, ctx, command, "web", "الاستخدام: /search كلمات البحث")


@router.message(Command("images"))
async def cmd_images(message: Message, ctx: AppContext, command: CommandObject) -> None:
    await _do_search(message, ctx, command, "images", "الاستخدام: /images كلمات البحث")


@router.message(Command("videos"))
async def cmd_videos(message: Message, ctx: AppContext, command: CommandObject) -> None:
    await _do_search(message, ctx, command, "videos", "الاستخدام: /videos كلمات البحث")


@router.message(Command("news"))
async def cmd_news(message: Message, ctx: AppContext, command: CommandObject) -> None:
    await _do_search(message, ctx, command, "news", "الاستخدام: /news كلمات البحث")


# -------------------------------------------------------------- reverse image
def _make_photo_url_factory(bot: Bot, ctx: AppContext, photo: PhotoSize):
    async def factory() -> str:
        if photo.file_size and photo.file_size > MAX_PHOTO_BYTES:
            raise SearchError("⚠️ الصورة كبيرة جداً للبحث العكسي.", "photo too large")
        try:
            file = await bot.get_file(photo.file_id)
            if not file.file_path:
                raise SearchError("⚠️ تعذّر قراءة الصورة من تيليجرام.", "no file_path")
            if ctx.settings.image_host == "telegram":
                return f"https://api.telegram.org/file/bot{ctx.settings.telegram_bot_token}/{file.file_path}"
            buffer = io.BytesIO()
            await bot.download_file(file.file_path, destination=buffer)
        except TelegramAPIError as exc:
            raise SearchError("⚠️ تعذّر تنزيل الصورة من تيليجرام.", f"telegram error: {exc}") from None
        return await upload_temp_image(
            ctx.session, buffer.getvalue(), "image.jpg", ctx.settings.search_timeout_seconds
        )

    return factory


async def _reverse_with_photo(message: Message, ctx: AppContext, photo: PhotoSize) -> None:
    user = to_user(message)
    async with ChatActionSender.typing(chat_id=message.chat.id, bot=message.bot):
        resp = await core.run_search(ctx, user, "reverse", _make_photo_url_factory(message.bot, ctx, photo))
    await _send_search_response(message, resp)


@router.message(Command("reverse"))
async def cmd_reverse(message: Message, ctx: AppContext, command: CommandObject) -> None:
    # A photo whose caption is "/reverse" also matches the Command filter.
    if message.photo:
        await _reverse_with_photo(message, ctx, message.photo[-1])
        return

    arg = (command.args or "").strip()
    if arg:
        if not re.match(r"^https?://\S+$", arg):
            await send_text(message, "⚠️ أرسل رابط صورة مباشر يبدأ بـ http أو https.")
            return
        user = to_user(message)
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=message.bot):
            resp = await core.run_search(ctx, user, "reverse", arg)
        await _send_search_response(message, resp)
        return

    replied = message.reply_to_message
    if replied and replied.photo:
        await _reverse_with_photo(message, ctx, replied.photo[-1])
        return

    await send_text(
        message,
        "🧬 البحث العكسي بالصورة:\n"
        "• أرسل صورة وفي التعليق اكتب /reverse\n"
        "• أو ردّ على صورة بالأمر /reverse\n"
        "• أو /reverse رابط_الصورة",
    )


@router.message(F.photo)
async def on_photo(message: Message, ctx: AppContext) -> None:
    caption = (message.caption or "").strip().lower()
    if caption.startswith("/reverse"):
        await _reverse_with_photo(message, ctx, message.photo[-1])  # type: ignore[index]
    elif _is_private(message):
        await send_text(
            message,
            "🖼 استلمت الصورة. للبحث العكسي أعد إرسالها مع التعليق /reverse، أو ردّ عليها بـ /reverse.",
        )


# --------------------------------------------------------------------- errors
async def on_error(event: ErrorEvent) -> bool:
    """Global error handler: nothing the user does should crash the bot."""
    exc = event.exception
    message = event.update.message

    if isinstance(exc, UserFacingError):
        if exc.text and message:
            await send_text(message, exc.text)
        return True

    if isinstance(exc, TelegramRetryAfter):
        log.warning("Flood control from Telegram: retry after %ss", exc.retry_after)
        return True
    if isinstance(exc, TelegramForbiddenError):
        return True

    log.error("Unhandled exception in handler", exc_info=exc)
    if message:
        try:
            await send_text(message, "⚠️ حدث خطأ غير متوقع. حاول مرة أخرى بعد قليل.")
        except Exception:  # pragma: no cover
            pass
    return True
