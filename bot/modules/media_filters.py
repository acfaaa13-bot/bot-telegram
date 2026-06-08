from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, is_staff, get_user_rank
import database as db


MEDIA_KEYS = [
    ("photos", "الصور"),
    ("videos", "الفيديو"),
    ("gifs", "المتحركة GIF"),
    ("stickers", "الملصقات"),
    ("files", "الملفات"),
    ("links", "الروابط"),
    ("notifications", "الإشعارات"),
    ("voice", "الرسائل الصوتية"),
    ("video_note", "الفيديو الدائري"),
    ("contacts", "جهات الاتصال"),
]


def _media_keyboard(group_id: int) -> object:
    group = db.get_group(group_id)
    filters = group.get("media_filters", {})
    rows = []
    for i in range(0, len(MEDIA_KEYS), 2):
        row = []
        for key, label in MEDIA_KEYS[i : i + 2]:
            locked = filters.get(key, False)
            style = "danger" if locked else "success"
            state = "قفل" if locked else "فتح"
            row.append(btn(f"{label} ◈ {state}", f"media_toggle_{key}", style=style))
        rows.append(row)
    rows.append([btn("◀ رجوع", "media_back", style="danger")])
    return keyboard(rows)


def _main_media_kb() -> object:
    return keyboard([
        [
            btn("الوسائط الممنوعة", "media_status", style="primary"),
            btn("تعديل الوسائط", "media_edit", style="primary"),
        ]
    ])


async def cmd_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = (
        "<b>❖ نظام الوسائط</b>\n\n"
        "<blockquote>يمكنك من خلال هذه القائمة عرض وتعديل حالة الوسائط في المجموعة.</blockquote>"
    )
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_media_kb())


async def callback_media_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = db.get_group(query.message.chat_id)
    filters = group.get("media_filters", {})
    lines = []
    for key, label in MEDIA_KEYS:
        state = "قفل" if filters.get(key, False) else "فتح"
        lines.append(f"➔ {label}: <b>{state}</b>")
    text = "<b>❖ حالة الوسائط الحالية:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>"
    kb = keyboard([[btn("◀ رجوع", "media_back", style="danger")]])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def callback_media_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    rank = await get_user_rank(chat_id, user_id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ هذه القائمة متاحة للمالك والمنشئ فقط.", show_alert=True)
        return
    await query.answer()
    kb = _media_keyboard(chat_id)
    await query.edit_message_text(
        "<b>❖ تعديل الوسائط:</b>\n<blockquote>اضغط على أي نوع وسائط لتغيير حالته.</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def callback_media_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    rank = await get_user_rank(chat_id, user_id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ ليس لديك صلاحية.", show_alert=True)
        return
    await query.answer()
    key = query.data.replace("media_toggle_", "")
    group = db.get_group(chat_id)
    filters = group.get("media_filters", {})
    filters[key] = not filters.get(key, False)
    db.groups_col.update_one(
        {"group_id": chat_id},
        {"$set": {"media_filters": filters}},
    )
    kb = _media_keyboard(chat_id)
    await query.edit_message_reply_markup(reply_markup=kb)


async def callback_media_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "<b>❖ نظام الوسائط</b>\n\n"
        "<blockquote>يمكنك من خلال هذه القائمة عرض وتعديل حالة الوسائط في المجموعة.</blockquote>"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_media_kb())


def _has_link(message: Message) -> bool:
    if message.entities:
        for e in message.entities:
            if e.type in ("url", "text_link", "mention"):
                return True
    return False


async def filter_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.chat:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return

    chat_id = msg.chat_id
    user_id = msg.from_user.id if msg.from_user else None
    if not user_id:
        return

    if await is_staff(chat_id, user_id, context):
        return

    group = db.get_group(chat_id)
    filters = group.get("media_filters", {})

    should_delete = False
    if filters.get("photos") and msg.photo:
        should_delete = True
    elif filters.get("videos") and msg.video:
        should_delete = True
    elif filters.get("gifs") and msg.animation:
        should_delete = True
    elif filters.get("stickers") and msg.sticker:
        should_delete = True
    elif filters.get("files") and msg.document:
        should_delete = True
    elif filters.get("links") and _has_link(msg):
        should_delete = True
    elif filters.get("voice") and msg.voice:
        should_delete = True
    elif filters.get("video_note") and msg.video_note:
        should_delete = True
    elif filters.get("contacts") and msg.contact:
        should_delete = True

    if should_delete:
        try:
            await msg.delete()
        except Exception:
            pass
        return True

    if filters.get("notifications") and (msg.new_chat_members or msg.left_chat_member):
        try:
            await msg.delete()
        except Exception:
            pass

    return False


async def filter_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    chat_id = msg.chat_id
    group = db.get_group(chat_id)
    filters = group.get("media_filters", {})
    if filters.get("notifications"):
        try:
            await msg.delete()
        except Exception:
            pass
