"""
YouTube Music Download & Search System.
Commands: تحميل [query], يوت [query], بحث [query]
Callbacks: dl_audio_{video_id}
"""
import os
import asyncio
import tempfile
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank
import database as db

logger = logging.getLogger(__name__)

DURATION_LIMIT = 600   # 10 minutes in seconds
SIZE_LIMIT = 50 * 1024 * 1024   # 50 MB

_YTDL_BASE = {
    "format": "bestaudio/best",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192",
    }],
    "outtmpl": "%(id)s.%(ext)s",
    "writethumbnail": True,
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
}


# ── Helpers ───────────────────────────────────────────────

def _search_yt(query: str, max_results: int = 1) -> list[dict]:
    """Synchronous yt-dlp search — run in thread pool."""
    import yt_dlp  # type: ignore
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        return info.get("entries", []) if info else []


def _download_audio(video_id: str, out_dir: str) -> tuple[str | None, str | None, dict]:
    """Synchronous download — returns (mp3_path, thumb_path, info_dict)."""
    import yt_dlp  # type: ignore
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = dict(_YTDL_BASE)
    opts["outtmpl"] = str(Path(out_dir) / "%(id)s.%(ext)s")

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    mp3 = str(Path(out_dir) / f"{video_id}.mp3")
    thumb = None
    for ext in ("jpg", "webp", "png"):
        p = str(Path(out_dir) / f"{video_id}.{ext}")
        if os.path.exists(p):
            thumb = p
            break
    return (mp3 if os.path.exists(mp3) else None, thumb, info or {})


async def _send_audio(context: ContextTypes.DEFAULT_TYPE, chat_id: int, video_id: str,
                      title: str, reply_msg_id: int | None = None):
    """Full download-cache-send pipeline."""
    # Cache hit
    cached = db.get_cached_music(video_id)
    if cached.get("file_id"):
        bot_username = (await context.bot.get_me()).username
        await context.bot.send_audio(
            chat_id,
            audio=cached["file_id"],
            caption=f"<b>❖ تم التحميل بنجاح بواسطة : @{esc(bot_username)}</b>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_msg_id,
        )
        return

    # Download in thread
    with tempfile.TemporaryDirectory() as tmp:
        try:
            mp3_path, thumb_path, info = await asyncio.to_thread(_download_audio, video_id, tmp)
        except Exception as e:
            await context.bot.send_message(
                chat_id,
                f"<b>◈ فشل التحميل:</b>\n<blockquote>{esc(str(e)[:300])}</blockquote>",
                parse_mode=ParseMode.HTML,
            )
            return

        if not mp3_path:
            await context.bot.send_message(
                chat_id,
                "<b>◈ لم يتم العثور على ملف الصوت بعد المعالجة.</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Size check
        size = os.path.getsize(mp3_path)
        if size > SIZE_LIMIT:
            await context.bot.send_message(
                chat_id,
                "<b>◈ حجم الملف يتجاوز 50 ميجابايت — التحميل ملغى.</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        bot_username = (await context.bot.get_me()).username
        clean_title = info.get("title", title) or title

        try:
            with open(mp3_path, "rb") as audio_f:
                thumb_f = open(thumb_path, "rb") if thumb_path else None
                try:
                    sent = await context.bot.send_audio(
                        chat_id,
                        audio=audio_f,
                        thumbnail=thumb_f,
                        title=clean_title,
                        filename=f"{clean_title}.mp3",
                        caption=f"<b>❖ تم التحميل بنجاح بواسطة : @{esc(bot_username)}</b>",
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=reply_msg_id,
                    )
                finally:
                    if thumb_f:
                        thumb_f.close()

            # Cache the file_id
            if sent and sent.audio:
                db.set_music_cache(video_id, sent.audio.file_id, clean_title, info.get("duration", 0))
        except Exception as e:
            await context.bot.send_message(
                chat_id,
                f"<b>◈ خطأ أثناء الإرسال:</b>\n<blockquote>{esc(str(e)[:300])}</blockquote>",
                parse_mode=ParseMode.HTML,
            )


async def _validate_and_download(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  query: str, video_id: str | None = None):
    """Shared pipeline: find top result if no video_id given, validate, send."""
    msg = update.message or update.effective_message
    chat_id = msg.chat_id if msg else update.effective_chat.id
    reply_id = msg.message_id if msg else None

    waiting = await context.bot.send_message(
        chat_id,
        "<b>◈ جارٍ البحث والتحميل...</b>",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Search if no video_id
        if not video_id:
            results = await asyncio.to_thread(_search_yt, query, 1)
            if not results:
                await waiting.edit_text("<b>◈ لا نتائج لهذا البحث.</b>", parse_mode=ParseMode.HTML)
                return
            entry = results[0]
            video_id = entry.get("id")
            if not video_id:
                await waiting.edit_text("<b>◈ لم يتم استخراج معرف الفيديو.</b>", parse_mode=ParseMode.HTML)
                return
            duration = entry.get("duration") or 0
            title = entry.get("title", query)
        else:
            # Validate from cache or quick info fetch
            cached = db.get_cached_music(video_id)
            duration = cached.get("duration", 0)
            title = cached.get("title", video_id)
            if not cached.get("duration"):
                def _get_info():
                    import yt_dlp  # type: ignore
                    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        return ydl.extract_info(url, download=False)
                info = await asyncio.to_thread(_get_info)
                duration = (info or {}).get("duration", 0)
                title = (info or {}).get("title", video_id)

        # Duration check
        if duration and duration > DURATION_LIMIT:
            mins = duration // 60
            await waiting.edit_text(
                f"<b>◈ مدة الفيديو ({mins} دقيقة) تتجاوز الحد المسموح (10 دقائق) — ملغى.</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        await waiting.delete()
        await _send_audio(context, chat_id, video_id, title, reply_id)

    except Exception as e:
        try:
            await waiting.edit_text(
                f"<b>◈ خطأ: {esc(str(e)[:300])}</b>", parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


# ── Command handlers ──────────────────────────────────────

async def cmd_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحميل [query] / يوت [query]"""
    msg = update.message
    if not context.args:
        await msg.reply_text("<b>◈ مثال: تحميل اسم الأغنية</b>", parse_mode=ParseMode.HTML)
        return
    query = " ".join(context.args)
    await _validate_and_download(update, context, query)


async def cmd_search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بحث [query] — shows top 5 results as inline buttons."""
    msg = update.message
    if not context.args:
        await msg.reply_text("<b>◈ مثال: بحث اسم الأغنية</b>", parse_mode=ParseMode.HTML)
        return
    query = " ".join(context.args)

    waiting = await msg.reply_text("<b>◈ جارٍ البحث...</b>", parse_mode=ParseMode.HTML)
    results = await asyncio.to_thread(_search_yt, query, 5)
    if not results:
        await waiting.edit_text("<b>◈ لا نتائج لهذا البحث.</b>", parse_mode=ParseMode.HTML)
        return

    styles = ["primary", "success"]
    rows = []
    for i, entry in enumerate(results[:5]):
        vid = entry.get("id", "")
        title = (entry.get("title") or "—")[:50]
        dur_raw = entry.get("duration")
        dur_str = f" [{dur_raw//60}:{dur_raw%60:02d}]" if dur_raw else ""
        style = styles[i % 2]
        rows.append([btn(f"{title}{dur_str}", f"dl_audio_{vid}", style=style)])

    rows.append([btn("◀ رجوع", "yt_search_back", style="danger")])
    await waiting.edit_text(
        f"<b>❖ نتائج البحث: {esc(query)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(rows),
    )


async def callback_dl_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dl_audio_{video_id}"""
    query = update.callback_query
    await query.answer("◈ جارٍ التحميل...")
    video_id = query.data[len("dl_audio_"):]
    try:
        await query.message.delete()
    except Exception:
        pass
    await _validate_and_download(update, context, video_id, video_id=video_id)


async def callback_yt_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("<b>◈ تم الإغلاق.</b>", parse_mode=ParseMode.HTML)
