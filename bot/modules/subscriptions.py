"""
Dual-layer mandatory subscription:
  - Layer 1 (Dev):   configured via /panel → "تعيين الاشتراك الإجباري"
                     targets: groups / pv / both — global on/off toggle.
  - Layer 2 (Group): configured by owner/creator via text commands:
                     تعيين الاشتراك الثانوي [@ch] | حذف قناه | تعطيل الاشتراك الثانوي
"""
from telegram import Update, ChatMember
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank, is_staff
import database as db


def _resolve_ref(ref: str):
    ref = ref.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if ref.startswith(prefix):
            part = ref[len(prefix):].split("/")[0]
            return f"@{part}" if part != "c" else ref
    if ref.lstrip("-").isdigit():
        return int(ref)
    return ref if ref.startswith("@") else f"@{ref}"


# ── Layer 2: Group-owner commands ────────────────────────

async def cmd_set_secondary_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك والمنشئ فقط.</b>", parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await msg.reply_text(
            "<b>◈ الاستخدام: تعيين الاشتراك الثانوي [@قناة أو رابط أو معرف]</b>",
            parse_mode=ParseMode.HTML,
        )
        return
    ref = _resolve_ref(" ".join(context.args))
    try:
        chat = await context.bot.get_chat(ref)
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
        if me.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
            await msg.reply_text("<b>◈ البوت ليس مشرفاً في تلك القناة.</b>", parse_mode=ParseMode.HTML)
            return
        link = f"https://t.me/{chat.username}" if chat.username else str(ref)
        db.groups_col.update_one(
            {"group_id": msg.chat_id},
            {"$set": {
                "secondary_sub_enabled": True,
                "secondary_channel_id": chat.id,
                "secondary_channel_link": link,
            }},
        )
        await msg.reply_text(
            f"<b>✦ تم تعيين الاشتراك الثانوي</b>\n\n"
            f"<blockquote>➔ القناة: <b>{esc(chat.title)}</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)


async def cmd_delete_secondary_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    db.groups_col.update_one(
        {"group_id": msg.chat_id},
        {"$set": {
            "secondary_sub_enabled": False,
            "secondary_channel_id": None,
            "secondary_channel_link": None,
        }},
    )
    await msg.reply_text(
        "<b>▼ تم حذف قناة الاشتراك الثانوي.</b>", parse_mode=ParseMode.HTML
    )


async def cmd_disable_secondary_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    db.groups_col.update_one(
        {"group_id": msg.chat_id},
        {"$set": {"secondary_sub_enabled": False}},
    )
    await msg.reply_text(
        "<b>▼ تم تعطيل الاشتراك الثانوي.</b>\n\n"
        "<blockquote>➔ بيانات القناة محفوظة — يمكن إعادة التفعيل لاحقاً.</blockquote>",
        parse_mode=ParseMode.HTML,
    )


# Legacy aliases kept for backward compat with normalizer routes
async def cmd_mandatory_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_set_secondary_sub(update, context)


async def cmd_modify_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_set_secondary_sub(update, context)


async def cmd_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_delete_secondary_channel(update, context)


async def cmd_disable_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_disable_secondary_sub(update, context)


# ── Check middleware ──────────────────────────────────────

async def _is_subscribed(bot, channel_id, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status not in (ChatMember.LEFT, ChatMember.BANNED)
    except Exception:
        return True  # assume subscribed on error


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Group message middleware. Returns False and handles the message if any layer fails."""
    msg = update.message
    if not msg or not msg.chat:
        return True
    if msg.chat.type not in ("group", "supergroup"):
        return True
    chat_id = msg.chat_id
    user_id = msg.from_user.id if msg.from_user else None
    if not user_id:
        return True
    if await is_staff(chat_id, user_id, context):
        return True

    missing = []

    # Layer 1: developer subscription (groups / both)
    dev_sub = db.get_dev_sub()
    if dev_sub.get("enabled") and dev_sub.get("channel_id"):
        if dev_sub.get("target", "both") in ("groups", "both"):
            if not await _is_subscribed(context.bot, dev_sub["channel_id"], user_id):
                missing.append(("قناة المطور", dev_sub.get("channel_link", "")))

    # Layer 2: group secondary subscription
    group = db.get_group(chat_id)
    if group.get("secondary_sub_enabled") and group.get("secondary_channel_id"):
        if not await _is_subscribed(context.bot, group["secondary_channel_id"], user_id):
            missing.append(("قناة المجموعة", group.get("secondary_channel_link", "")))

    if not missing:
        return True

    try:
        await msg.delete()
    except Exception:
        pass

    buttons = [[btn(label, url=link, style="primary") for label, link in missing if link]]
    text = (
        "<b>❖ يجب عليك الاشتراك في القنوات التالية للتحدث:</b>\n\n"
        "<blockquote>" + "\n".join(f"➔ {label}" for label, _ in missing) + "</blockquote>"
    )
    try:
        await context.bot.send_message(
            chat_id, text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(buttons) if buttons and buttons[0] else None,
        )
    except Exception:
        pass
    return False


async def check_pv_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """PV message middleware. Returns False if dev subscription (pv / both) fails."""
    msg = update.message
    if not msg or msg.chat.type != "private":
        return True
    user_id = msg.from_user.id

    dev_sub = db.get_dev_sub()
    if dev_sub.get("enabled") and dev_sub.get("channel_id"):
        if dev_sub.get("target", "both") in ("pv", "both"):
            if not await _is_subscribed(context.bot, dev_sub["channel_id"], user_id):
                link = dev_sub.get("channel_link", "")
                kb = keyboard([[btn("قناة المطور", url=link, style="primary")]]) if link else None
                await msg.reply_text(
                    "<b>❖ يجب عليك الاشتراك في قناة المطور للمتابعة.</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
                return False
    return True
