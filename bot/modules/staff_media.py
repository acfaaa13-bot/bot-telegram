"""
Staff Media Control Panel (وسائط الادمن).
Owner/Creator can restrict specific media types for individual admins/moderators.
Even staff with native Telegram permissions get their messages deleted if a media
type is blocked for them specifically.
"""
from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank, is_higher_rank
import database as db

STAFF_MEDIA_KEYS = [
    ("photos", "الصور"),
    ("videos", "الفيديو"),
    ("gifs", "المتحركة GIF"),
    ("stickers", "الملصقات"),
    ("files", "الملفات"),
    ("links", "الروابط"),
    ("voice", "الرسائل الصوتية"),
    ("video_note", "الفيديو الدائري"),
    ("contacts", "جهات الاتصال"),
]


def _staff_media_kb(group_id: int, target_id: int) -> object:
    locks = db.get_staff_media_locks(group_id, target_id)
    rows = []
    for i in range(0, len(STAFF_MEDIA_KEYS), 2):
        row = []
        for key, label in STAFF_MEDIA_KEYS[i : i + 2]:
            blocked = locks.get(key, False)
            row.append(btn(
                f"{label} ◈ {'محظور' if blocked else 'مسموح'}",
                f"smedia_{target_id}_{key}",
                style="danger" if blocked else "success",
            ))
        rows.append(row)
    rows.append([btn("◀ رجوع", "smedia_back", style="danger")])
    return keyboard(rows)


async def cmd_staff_media_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك والمنشئ فقط.</b>", parse_mode=ParseMode.HTML)
        return

    target_id, target_username, target_name = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ الاستخدام: وسائط الادمن (رداً على رسالة) أو وسائط الادمن [معرف]</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_rank = await get_user_rank(chat_id, target_id, context)
    if target_rank not in ("admin", "moderator", "creator"):
        await msg.reply_text(
            "<b>❖ يجب أن يكون المستخدم أدمن أو مشرف أو منشئ.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    display = f"@{target_username}" if target_username else esc(target_name or str(target_id))
    context.chat_data[f"smedia_target_{msg.from_user.id}"] = target_id

    kb = _staff_media_kb(chat_id, target_id)
    await msg.reply_text(
        f"<b>❖ وسائط الادمن</b>\n\n"
        f"<blockquote>➔ المستخدم: <b>{display}</b>\n"
        f"➔ اضغط على نوع الوسائط لتفعيل/إلغاء القيد.</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def callback_staff_media_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    actor_rank = await get_user_rank(chat_id, query.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        await query.answer("❖ ليس لديك صلاحية.", show_alert=True)
        return
    await query.answer()

    parts = query.data.split("_", 2)
    # pattern: smedia_{target_id}_{key}
    target_id = int(parts[1])
    media_key = parts[2]

    locks = db.get_staff_media_locks(chat_id, target_id)
    locks[media_key] = not locks.get(media_key, False)
    db.set_staff_media_locks(chat_id, target_id, locks)

    await query.edit_message_reply_markup(reply_markup=_staff_media_kb(chat_id, target_id))


async def callback_staff_media_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("<b>❖ تم الإغلاق.</b>", parse_mode=ParseMode.HTML)


async def filter_staff_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Called after the regular media filter. Checks staff-specific restrictions.
    Returns True (and deletes message) if a blocked media type was sent by a staff member.
    """
    msg = update.message
    if not msg or not msg.from_user:
        return False
    if msg.chat.type not in ("group", "supergroup"):
        return False

    chat_id = msg.chat_id
    user_id = msg.from_user.id

    locks = db.get_staff_media_locks(chat_id, user_id)
    if not locks:
        return False

    def _has_link(m: Message) -> bool:
        if m.entities:
            for e in m.entities:
                if e.type in ("url", "text_link", "mention"):
                    return True
        return False

    should_delete = (
        (locks.get("photos") and msg.photo) or
        (locks.get("videos") and msg.video) or
        (locks.get("gifs") and msg.animation) or
        (locks.get("stickers") and msg.sticker) or
        (locks.get("files") and msg.document) or
        (locks.get("links") and _has_link(msg)) or
        (locks.get("voice") and msg.voice) or
        (locks.get("video_note") and msg.video_note) or
        (locks.get("contacts") and msg.contact)
    )

    if should_delete:
        try:
            await msg.delete()
        except Exception:
            pass
        return True

    return False


async def _resolve_target(msg, context):
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.username, u.full_name
    if context.args:
        try:
            uid = int(context.args[0])
            try:
                cm = await context.bot.get_chat_member(msg.chat_id, uid)
                u = cm.user
                return u.id, u.username, u.full_name
            except Exception:
                return uid, None, str(uid)
        except ValueError:
            pass
    return None, None, None
