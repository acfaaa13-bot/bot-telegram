import random
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank
import database as db

STEP_KEYWORD, STEP_RESPONSE = range(2)
EDIT_STEP_KEYWORD, EDIT_STEP_RESPONSE = range(10, 12)


async def cmd_add_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك والمنشئ فقط.</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    context.user_data["response_chat_id"] = msg.chat_id
    kb = keyboard([[btn("إلغاء العملية", "cancel_response", style="danger")]])
    await msg.reply_text(
        "<b>❖ أضافة رد تلقائي</b>\n\n<blockquote>➔ أرسل الكلمة المفتاحية:</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return STEP_KEYWORD


async def step_receive_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    keyword = msg.text.strip().lower() if msg.text else None
    if not keyword:
        await msg.reply_text("<b>◈ يرجى إرسال نص للكلمة المفتاحية.</b>", parse_mode=ParseMode.HTML)
        return STEP_KEYWORD
    chat_id = context.user_data.get("response_chat_id", msg.chat_id)
    existing = db.custom_responses_col.find_one({"group_id": chat_id, "keyword": keyword})
    if existing:
        await msg.reply_text(
            f"<b>◈ الكلمة <code>{esc(keyword)}</code> موجودة بالفعل. استخدم تعديل رد أو حذف رد أولاً.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    context.user_data["new_keyword"] = keyword
    kb = keyboard([[btn("إلغاء العملية", "cancel_response", style="danger")]])
    await msg.reply_text(
        f"<b>✦ الكلمة:</b> <code>{esc(keyword)}</code>\n\n<blockquote>➔ الآن أرسل الرد (نص، صورة، أو ملصق):</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return STEP_RESPONSE


async def step_receive_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = context.user_data.get("response_chat_id", msg.chat_id)
    keyword = context.user_data.get("new_keyword", "")

    reply_type, content, caption = _extract_content(msg)
    if reply_type is None:
        await msg.reply_text("<b>◈ نوع الرسالة غير مدعوم.</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    db.custom_responses_col.insert_one({
        "group_id": chat_id,
        "keyword": keyword,
        "reply_type": reply_type,
        "content": content,
        "caption": caption,
    })
    await msg.reply_text(
        f"<b>✦ تمت الإضافة بنجاح</b>\n\n<blockquote>➔ الكلمة: <code>{esc(keyword)}</code>\n➔ النوع: <b>{reply_type}</b></blockquote>",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cmd_edit_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك والمنشئ فقط.</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    context.user_data["response_chat_id"] = msg.chat_id
    kb = keyboard([[btn("إلغاء العملية", "cancel_response", style="danger")]])
    await msg.reply_text(
        "<b>❖ تعديل رد</b>\n\n<blockquote>➔ أرسل الكلمة المفتاحية المراد تعديلها:</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return EDIT_STEP_KEYWORD


async def edit_step_receive_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    keyword = msg.text.strip().lower() if msg.text else None
    chat_id = context.user_data.get("response_chat_id", msg.chat_id)
    existing = db.custom_responses_col.find_one({"group_id": chat_id, "keyword": keyword})
    if not existing:
        await msg.reply_text(
            f"<b>◈ الكلمة <code>{esc(keyword)}</code> غير موجودة.</b>", parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END
    context.user_data["edit_keyword"] = keyword
    kb = keyboard([[btn("إلغاء العملية", "cancel_response", style="danger")]])
    await msg.reply_text(
        f"<b>✦ الكلمة:</b> <code>{esc(keyword)}</code>\n\n<blockquote>➔ أرسل الرد الجديد:</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return EDIT_STEP_RESPONSE


async def edit_step_receive_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = context.user_data.get("response_chat_id", msg.chat_id)
    keyword = context.user_data.get("edit_keyword", "")

    reply_type, content, caption = _extract_content(msg)
    if reply_type is None:
        await msg.reply_text("<b>◈ نوع الرسالة غير مدعوم.</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    db.custom_responses_col.update_one(
        {"group_id": chat_id, "keyword": keyword},
        {"$set": {"reply_type": reply_type, "content": content, "caption": caption}},
    )
    await msg.reply_text(
        f"<b>✦ تم التعديل بنجاح</b>\n\n<blockquote>➔ الكلمة: <code>{esc(keyword)}</code></blockquote>",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cmd_delete_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك والمنشئ فقط.</b>", parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await msg.reply_text("<b>◈ الاستخدام: حذف رد [الكلمة]</b>", parse_mode=ParseMode.HTML)
        return
    keyword = " ".join(context.args).strip().lower()
    result = db.custom_responses_col.delete_one({"group_id": msg.chat_id, "keyword": keyword})
    if result.deleted_count:
        await msg.reply_text(
            f"<b>✦ تم حذف الرد للكلمة:</b> <code>{esc(keyword)}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.reply_text(
            f"<b>◈ الكلمة <code>{esc(keyword)}</code> غير موجودة.</b>", parse_mode=ParseMode.HTML
        )


async def cancel_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("<b>◈ تم إلغاء العملية.</b>", parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text("<b>◈ تم إلغاء العملية.</b>", parse_mode=ParseMode.HTML)
    return ConversationHandler.END


def _extract_content(msg):
    """Returns (reply_type, content, caption) or (None, '', '') on unsupported."""
    if msg.photo:
        return "photo", msg.photo[-1].file_id, msg.caption or ""
    if msg.sticker:
        return "sticker", msg.sticker.file_id, ""
    if msg.text:
        return "text", msg.text, ""
    return None, "", ""


async def trigger_keyword_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return

    text = msg.text.strip().lower()
    chat_id = msg.chat_id
    doc = db.custom_responses_col.find_one({"group_id": chat_id, "keyword": text})
    if not doc:
        return

    try:
        if doc["reply_type"] == "text":
            content = doc["content"].replace("#username", esc(msg.from_user.full_name))
            await msg.reply_html(content)
        elif doc["reply_type"] == "photo":
            await context.bot.send_photo(
                chat_id,
                photo=doc["content"],
                caption=doc.get("caption", ""),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=msg.message_id,
            )
        elif doc["reply_type"] == "sticker":
            await context.bot.send_sticker(
                chat_id,
                sticker=doc["content"],
                reply_to_message_id=msg.message_id,
            )
    except Exception:
        pass


def get_add_conversation_handler():
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^اضافة رد$") & filters.ChatType.GROUPS, cmd_add_response)],
        states={
            STEP_KEYWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_receive_keyword),
                CallbackQueryHandler(cancel_response, pattern="^cancel_response$"),
            ],
            STEP_RESPONSE: [
                MessageHandler(filters.ALL & ~filters.COMMAND, step_receive_response),
                CallbackQueryHandler(cancel_response, pattern="^cancel_response$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_response, pattern="^cancel_response$")],
        per_user=True,
        per_chat=True,
        per_message=False,
    )


def get_edit_conversation_handler():
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^تعديل رد$") & filters.ChatType.GROUPS, cmd_edit_response)],
        states={
            EDIT_STEP_KEYWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_step_receive_keyword),
                CallbackQueryHandler(cancel_response, pattern="^cancel_response$"),
            ],
            EDIT_STEP_RESPONSE: [
                MessageHandler(filters.ALL & ~filters.COMMAND, edit_step_receive_response),
                CallbackQueryHandler(cancel_response, pattern="^cancel_response$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_response, pattern="^cancel_response$")],
        per_user=True,
        per_chat=True,
        per_message=False,
    )
