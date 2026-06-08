import uuid
from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode
from utils import esc, btn, keyboard
import database as db

WHISPER_STATE = 0


async def cmd_whisper_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered when user replies with همسه / همسة in a group."""
    msg = update.message
    if not msg or not msg.reply_to_message:
        await msg.reply_text(
            "<b>◈ يجب الرد على رسالة المستخدم المراد مهامسته.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    target = msg.reply_to_message.from_user
    if not target or target.is_bot:
        await msg.reply_text(
            "<b>◈ لا يمكن إرسال همسة إلى بوت.</b>", parse_mode=ParseMode.HTML
        )
        return

    sender = msg.from_user
    bot_username = context.bot.username
    group_id = msg.chat_id
    payload = f"whisper_{target.id}_{group_id}"
    deep_link = f"https://t.me/{bot_username}?start={payload}"

    target_display = f"@{target.username}" if target.username else esc(target.full_name)
    text = (
        f"<b>❖ همسة</b>\n\n"
        f"<blockquote>➔ إلى: <b>{target_display}</b>\n"
        f"➔ اضغط الزر أدناه للانتقال إلى الخاص وكتابة همستك.</blockquote>"
    )
    kb = keyboard([[btn("➔ اكتب الهمسة في الخاص", url=deep_link, style="primary")]])
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def start_whisper_pv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point from deep link: /start whisper_TARGETID_GROUPID"""
    msg = update.message
    args = context.args
    if not args or not args[0].startswith("whisper_"):
        return ConversationHandler.END

    parts = args[0].split("_")
    if len(parts) != 3:
        return ConversationHandler.END

    try:
        target_id = int(parts[1])
        group_id = int(parts[2])
    except ValueError:
        return ConversationHandler.END

    context.user_data["whisper_target_id"] = target_id
    context.user_data["whisper_group_id"] = group_id

    try:
        target_chat = await context.bot.get_chat(target_id)
        target_name = target_chat.full_name or str(target_id)
    except Exception:
        target_name = str(target_id)

    await msg.reply_text(
        f"<b>❖ كتابة همسة</b>\n\n"
        f"<blockquote>➔ إلى: <b>{esc(target_name)}</b>\n"
        f"➔ اكتب نص همستك السرية:</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard([[btn("إلغاء", "cancel_whisper", style="danger")]]),
    )
    return WHISPER_STATE


async def receive_whisper_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        await msg.reply_text(
            "<b>◈ يرجى إرسال نص فقط للهمسة.</b>", parse_mode=ParseMode.HTML
        )
        return WHISPER_STATE

    target_id = context.user_data.get("whisper_target_id")
    group_id = context.user_data.get("whisper_group_id")
    sender = msg.from_user

    if not target_id or not group_id:
        return ConversationHandler.END

    whisper_id = str(uuid.uuid4())[:12]
    db.save_whisper(whisper_id, sender.id, target_id, group_id, msg.text)

    # Fetch target username for group message
    try:
        target_chat = await context.bot.get_chat(target_id)
        target_display = f"@{target_chat.username}" if target_chat.username else esc(target_chat.full_name or str(target_id))
    except Exception:
        target_display = str(target_id)

    sender_display = f"@{sender.username}" if sender.username else esc(sender.full_name)

    group_text = (
        f"<b>❖ المستخدم {target_display} وصلتلك همسة من {sender_display} اضغط على الزر أدناه لرؤية الهمسة</b>"
    )
    kb = keyboard([[btn("❖ إضغط لرؤية الهمسة ❖", f"whisper_{whisper_id}", style="success")]])

    try:
        await context.bot.send_message(
            group_id, group_text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    except Exception as e:
        await msg.reply_text(
            f"<b>◈ فشل إرسال الهمسة إلى المجموعة: {esc(str(e))}</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    await msg.reply_text(
        "<b>✦ تم إرسال الهمسة بنجاح.</b>", parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


async def cancel_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("<b>◈ تم إلغاء الهمسة.</b>", parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text("<b>◈ تم إلغاء الهمسة.</b>", parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def callback_view_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    whisper_id = query.data.replace("whisper_", "")
    doc = db.get_whisper(whisper_id)

    if not doc:
        await query.answer("❖ الهمسة غير موجودة أو انتهت صلاحيتها.", show_alert=True)
        return

    if query.from_user.id == doc["target_id"]:
        await query.answer(doc["content"], show_alert=True)
    else:
        await query.answer("❖ هذه الهمسة ليست لك", show_alert=True)


def get_whisper_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CommandHandler(
                "start",
                start_whisper_pv,
                filters=filters.ChatType.PRIVATE & filters.Regex(r"^/start whisper_"),
            )
        ],
        states={
            WHISPER_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_whisper_text),
                CallbackQueryHandler(cancel_whisper, pattern="^cancel_whisper$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_whisper, pattern="^cancel_whisper$")],
        per_user=True,
        per_chat=True,
        per_message=False,
    )
