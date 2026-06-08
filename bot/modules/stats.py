from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, get_user_rank, rank_badge, is_staff
import database as db
from config import DEVELOPER_ID


async def handle_bot_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.new_chat_members:
        return
    for member in msg.new_chat_members:
        if member.id == context.bot.id:
            chat = msg.chat
            db.groups_col.update_one(
                {"group_id": chat.id},
                {"$set": {
                    "join_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                    "title": chat.title,
                    "invite_link": chat.invite_link or "",
                }},
                upsert=True,
            )
            break


async def cmd_group_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not await is_staff(msg.chat_id, msg.from_user.id, context):
        return

    chat = msg.chat
    chat_id = msg.chat_id
    group = db.get_group(chat_id)

    try:
        member_count = await context.bot.get_chat_member_count(chat_id)
    except Exception:
        member_count = "غير متاح"

    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        owner = next((a for a in admins if a.status == "creator"), None)
        owner_name = owner.user.full_name if owner else "غير محدد"
    except Exception:
        owner_name = "غير محدد"

    creators_count = db.users_col.count_documents({"group_id": chat_id, "rank": "creator"})
    admins_count = db.users_col.count_documents({"group_id": chat_id, "rank": "admin"})
    mods_count = db.users_col.count_documents({"group_id": chat_id, "rank": "moderator"})
    muted_count = db.muted_users_col.count_documents({"group_id": chat_id})
    banned_count = db.banned_users_col.count_documents({"group_id": chat_id})

    join_date = group.get("join_date", "غير مسجل")

    text = (
        f"<b>❖ إحصائيات المجموعة</b>\n\n"
        f"<blockquote>"
        f"➔ الاسم: <b>{esc(chat.title)}</b>\n"
        f"➔ المعرف: <b>{chat_id}</b>\n"
        f"➔ المالك: <b>{esc(owner_name)}</b>\n"
        f"➔ تاريخ التفعيل: <b>{join_date}</b>\n"
        f"➔ عدد الأعضاء: <b>{member_count}</b>"
        f"</blockquote>\n\n"
        f"<b>◈ الإحصائيات الإدارية:</b>\n"
        f"<blockquote>"
        f"➔ المنشئون: <b>{creators_count}</b>\n"
        f"➔ الأدمنية: <b>{admins_count}</b>\n"
        f"➔ المشرفون: <b>{mods_count}</b>"
        f"</blockquote>\n\n"
        f"<b>▼ إحصائيات العقوبات:</b>\n"
        f"<blockquote>"
        f"➔ المكتومون: <b>{muted_count}</b>\n"
        f"➔ المحظورون: <b>{banned_count}</b>"
        f"</blockquote>"
    )
    await msg.reply_text(text, parse_mode=ParseMode.HTML)


async def track_pv_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat.type != "private":
        return
    user = msg.from_user
    db.pv_users_col.update_one(
        {"user_id": user.id},
        {"$set": {
            "user_id": user.id,
            "name": user.full_name,
            "username": user.username,
        }},
        upsert=True,
    )
