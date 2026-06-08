import time
from collections import defaultdict
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, is_staff, get_user_rank
import database as db

LOCK_KEYS = [
    ("usernames", "المعرفات"),
    ("forwarding", "التوجيه"),
    ("pinning", "التثبيت"),
    ("editing", "التعديل"),
    ("flood", "الفيضان"),
    ("chat", "قفل المجموعه"),
    ("mandatory_sub", "الاشتراك الاجباري"),
    ("bots", "البوتات"),
]

_flood_tracker: dict = defaultdict(list)


def _locks_keyboard(group_id: int) -> object:
    group = db.get_group(group_id)
    locks = group.get("locks", {})
    rows = []
    for i in range(0, len(LOCK_KEYS), 2):
        row = []
        for key, label in LOCK_KEYS[i : i + 2]:
            locked = locks.get(key, False)
            style = "danger" if locked else "success"
            state = "مقفول" if locked else "مفتوح"
            row.append(btn(f"{label} ◈ {state}", f"lock_toggle_{key}", style=style))
        rows.append(row)
    rows.append([btn("◀ رجوع", "lock_back", style="danger")])
    return keyboard(rows)


def _main_lock_kb() -> object:
    return keyboard([
        [
            btn("الاعدادات", "lock_status", style="primary"),
            btn("تعديل", "lock_edit", style="primary"),
        ]
    ])


async def cmd_group_protection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = (
        "<b>❖ نظام حماية المجموعة</b>\n\n"
        "<blockquote>يمكنك التحكم في قواعد الحماية والقيود من هنا.</blockquote>"
    )
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_lock_kb())


async def callback_lock_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = db.get_group(query.message.chat_id)
    locks = group.get("locks", {})
    lines = []
    for key, label in LOCK_KEYS:
        state = "مقفول" if locks.get(key, False) else "مفتوح"
        lines.append(f"➔ {label}: <b>{state}</b>")
    text = "<b>❖ حالة الحماية الحالية:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>"
    kb = keyboard([[btn("◀ رجوع", "lock_back", style="danger")]])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def callback_lock_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    rank = await get_user_rank(chat_id, query.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ هذه القائمة متاحة للمالك والمنشئ فقط.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        "<b>❖ تعديل إعدادات الحماية:</b>\n<blockquote>اضغط على أي قيد لتغيير حالته.</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=_locks_keyboard(chat_id),
    )


async def callback_lock_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    rank = await get_user_rank(chat_id, query.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ ليس لديك صلاحية.", show_alert=True)
        return
    await query.answer()
    key = query.data.replace("lock_toggle_", "")
    group = db.get_group(chat_id)
    locks = group.get("locks", {})
    locks[key] = not locks.get(key, False)
    db.groups_col.update_one({"group_id": chat_id}, {"$set": {"locks": locks}})
    await query.edit_message_reply_markup(reply_markup=_locks_keyboard(chat_id))


async def callback_lock_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "<b>❖ نظام حماية المجموعة</b>\n\n"
        "<blockquote>يمكنك التحكم في قواعد الحماية والقيود من هنا.</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_lock_kb(),
    )


async def enforce_locks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg = update.message or update.edited_message
    if not msg or not msg.chat:
        return False
    if msg.chat.type not in ("group", "supergroup"):
        return False

    chat_id = msg.chat_id
    user_id = msg.from_user.id if msg.from_user else None
    if not user_id:
        return False

    if await is_staff(chat_id, user_id, context):
        return False

    group = db.get_group(chat_id)
    locks = group.get("locks", {})

    # Editing lock
    if update.edited_message and locks.get("editing"):
        try:
            await msg.delete()
        except Exception:
            pass
        return True

    # Chat (group) lock — delete message + send warning
    if locks.get("chat"):
        try:
            await msg.delete()
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id,
                "<b>❖ عذراً، يمنع إرسال الرسائل في هذه المجموعة حالياً إلا لأصحاب الرتب.</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return True

    # Username lock
    if locks.get("usernames") and msg.text and "@" in msg.text:
        try:
            await msg.delete()
        except Exception:
            pass
        return True

    # Forwarding lock
    if locks.get("forwarding") and (msg.forward_date or msg.forward_origin):
        try:
            await msg.delete()
        except Exception:
            pass
        return True

    # Flood lock (basic rate limiter)
    if locks.get("flood"):
        now = time.time()
        key = (chat_id, user_id)
        _flood_tracker[key] = [t for t in _flood_tracker[key] if now - t < 3]
        _flood_tracker[key].append(now)
        if len(_flood_tracker[key]) > 4:
            try:
                await msg.delete()
            except Exception:
                pass
            return True

    return False


async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.new_chat_members:
        return
    chat_id = msg.chat_id
    adder_id = msg.from_user.id if msg.from_user else None
    group = db.get_group(chat_id)
    locks = group.get("locks", {})
    if locks.get("bots"):
        if adder_id and not await is_staff(chat_id, adder_id, context):
            for member in msg.new_chat_members:
                if member.is_bot:
                    try:
                        await context.bot.ban_chat_member(chat_id, member.id)
                    except Exception:
                        pass
