"""
Anti-spam & repetition engine.
  - Sliding-window spam detection: X messages in Y seconds → warn + delete spam burst.
  - Repetition lock: same message hash N times → temporary mute.
Both are in-memory per restart (intentional — lightweight & fast).
"""
import time
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, is_staff, get_user_rank
import database as db

# ── In-memory trackers ────────────────────────────────────
# spam: (chat_id, user_id) -> [(timestamp, message_id), ...]
_spam_tracker: dict = defaultdict(list)

# repetition: (chat_id, user_id) -> {hash: count}
_rep_tracker: dict = defaultdict(lambda: defaultdict(int))


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


async def check_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True and handles deletion+warning if spam detected."""
    msg = update.message or update.edited_message
    if not msg or not msg.from_user:
        return False
    if msg.chat.type not in ("group", "supergroup"):
        return False

    chat_id = msg.chat_id
    user_id = msg.from_user.id

    if await is_staff(chat_id, user_id, context):
        return False

    group = db.get_group(chat_id)
    spam_cfg = group.get("spam_config", {})
    window = spam_cfg.get("window", 5)
    threshold = spam_cfg.get("threshold", 6)

    key = (chat_id, user_id)
    now = time.time()

    # Prune entries outside the window
    _spam_tracker[key] = [(ts, mid) for ts, mid in _spam_tracker[key] if now - ts < window]
    _spam_tracker[key].append((now, msg.message_id))

    if len(_spam_tracker[key]) >= threshold:
        # Delete all tracked spam messages
        spam_msg_ids = [mid for _, mid in _spam_tracker[key]]
        _spam_tracker[key].clear()

        for mid in spam_msg_ids:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass

        # Issue auto-warning via punishments module
        from modules.punishments import _check_auto_mute
        await _check_auto_mute(chat_id, user_id, msg.from_user.username, context)

        name = f"@{msg.from_user.username}" if msg.from_user.username else str(user_id)
        try:
            await context.bot.send_message(
                chat_id,
                f"<b>▼ مكافحة السبام</b>\n\n"
                f"<blockquote>➔ <b>{esc(name)}</b> تجاوز حد الرسائل المسموح به.\n"
                f"➔ تم حذف {len(spam_msg_ids)} رسالة.</blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return True

    return False


async def check_repetition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True and mutes user if they repeat the same message beyond the limit."""
    msg = update.message
    if not msg or not msg.text or not msg.from_user:
        return False
    if msg.chat.type not in ("group", "supergroup"):
        return False

    chat_id = msg.chat_id
    user_id = msg.from_user.id

    if await is_staff(chat_id, user_id, context):
        return False

    group = db.get_group(chat_id)
    rep_limit = group.get("repetition_limit", 3)
    if rep_limit <= 0:
        return False

    key = (chat_id, user_id)
    h = _text_hash(msg.text)

    # Reset tracker if user sends a different message
    _rep_tracker[key] = {k: v for k, v in _rep_tracker[key].items() if k == h}
    _rep_tracker[key][h] = _rep_tracker[key].get(h, 0) + 1

    if _rep_tracker[key][h] >= rep_limit:
        _rep_tracker[key][h] = 0  # reset after triggering

        group = db.get_group(chat_id)
        dur = group.get("auto_mute", {}).get("mute_duration", 5)
        until = datetime.now() + timedelta(minutes=dur)

        try:
            await msg.delete()
        except Exception:
            pass

        try:
            await context.bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            db.register_muted(chat_id, user_id, msg.from_user.username, timed=True, until=until)
        except Exception:
            pass

        name = f"@{msg.from_user.username}" if msg.from_user.username else str(user_id)
        from modules.punishments import _unmute_kb
        try:
            await context.bot.send_message(
                chat_id,
                f"<b>▼ تكرار</b>\n\n"
                f"<blockquote>➔ <b>{esc(name)}</b> تجاوز حد التكرار.\n"
                f"➔ مكتوم لمدة <b>{dur}</b> دقيقة.</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=_unmute_kb(user_id),
            )
        except Exception:
            pass
        return True

    return False


async def cmd_set_spam_window(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    if not context.args:
        await msg.reply_text("<b>◈ مثال: تعيين مده اسبام 5</b>", parse_mode=ParseMode.HTML)
        return
    try:
        secs = int(context.args[0])
    except ValueError:
        await msg.reply_text("<b>◈ يجب إدخال رقم صحيح.</b>", parse_mode=ParseMode.HTML)
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"spam_config.window": secs}})
    await msg.reply_text(f"<b>✦ نافذة السبام: {secs} ثانية.</b>", parse_mode=ParseMode.HTML)


async def cmd_set_spam_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    if not context.args:
        await msg.reply_text("<b>◈ مثال: تعيين عدد السبام 6</b>", parse_mode=ParseMode.HTML)
        return
    try:
        count = int(context.args[0])
    except ValueError:
        await msg.reply_text("<b>◈ يجب إدخال رقم صحيح.</b>", parse_mode=ParseMode.HTML)
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"spam_config.threshold": count}})
    await msg.reply_text(f"<b>✦ حد السبام: {count} رسالة.</b>", parse_mode=ParseMode.HTML)


async def cmd_set_repetition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    if not context.args:
        await msg.reply_text("<b>◈ مثال: تعيين عدد التكرار 3</b>", parse_mode=ParseMode.HTML)
        return
    try:
        limit = int(context.args[0])
    except ValueError:
        await msg.reply_text("<b>◈ يجب إدخال رقم صحيح.</b>", parse_mode=ParseMode.HTML)
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"repetition_limit": limit}})
    await msg.reply_text(f"<b>✦ حد التكرار: {limit} مرة.</b>", parse_mode=ParseMode.HTML)
