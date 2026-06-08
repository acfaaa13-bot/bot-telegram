import sys
import os
import threading
import logging

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode

sys.path.insert(0, os.path.dirname(__file__))

from config import BOT_TOKEN, DEVELOPER_ID
import database as db
from utils import esc, btn, keyboard

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("telegram.ext.ConversationHandler").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# ── Flask uptime-ping server ──────────────────────────────
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is running", 200


def run_flask():
    flask_app.run(host="0.0.0.0", port=5001, use_reloader=False)


# ── Maintenance middleware ────────────────────────────────
async def maintenance_check(update: Update, context) -> bool:
    if not db.get_bot_status():
        user = update.effective_user
        if user and (user.id == DEVELOPER_ID or user.id in db.get_secondary_devs()):
            return True
        msg = update.message or update.edited_message
        if msg:
            try:
                await msg.reply_text(
                    "<b>❖ البوت في حالة صيانة مؤقتة حالياً...</b>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        return False
    return True


# ── Import all modules ────────────────────────────────────
from modules import ranks, media_filters, locks, punishments, stats, subscriptions, developer
from modules.antispam import check_spam, check_repetition
from modules.staff_media import (
    filter_staff_media,
    callback_staff_media_toggle,
    callback_staff_media_back,
)
from modules.keywords import (
    trigger_keyword_response,
    get_add_conversation_handler,
    get_edit_conversation_handler,
)
from modules.whispers import (
    get_whisper_conversation_handler,
    callback_view_whisper,
)
from modules.youtube import (
    callback_dl_audio,
    callback_yt_back,
)
from modules.games import (
    callback_quiz,
    callback_quiz_done,
    callback_xo_join,
    callback_xo_move,
    callback_math,
    callback_rps_join,
    callback_rps_pick,
    callback_mine,
    callback_guess,
)
from modules.normalizer import (
    cmd_start,
    cmd_main_menu,
    route_text_command,
    cmd_developer_profile,
    callback_help,
    callback_pv_menu,
)


# ── Shared message pipeline ───────────────────────────────
async def _run_group_pipeline(update: Update, context, is_edit: bool = False):
    """Full enforcement pipeline for both new and edited messages."""
    if not await maintenance_check(update, context):
        return

    ok = await subscriptions.check_subscription(update, context)
    if not ok:
        return

    msg = update.message if not is_edit else update.edited_message
    if not msg:
        return

    from utils import is_staff
    user_staff = msg.from_user and await is_staff(msg.chat_id, msg.from_user.id, context)

    # Staff-specific media locks (bypass normal staff immunity)
    if user_staff and msg.from_user:
        deleted = await filter_staff_media(update, context)
        if deleted:
            return

    if not user_staff:
        # Anti-spam sliding window
        spammed = await check_spam(update, context)
        if spammed:
            return

        # Repetition lock (new messages only)
        if not is_edit:
            repeated = await check_repetition(update, context)
            if repeated:
                return

        # Media filters
        deleted = await media_filters.filter_media(update, context)
        if deleted:
            if msg.from_user:
                await punishments.process_violation(msg.chat_id, msg.from_user.id, msg.from_user.username, context)
            return

        # Lock enforcement (includes chat lock, username lock, etc.)
        deleted = await locks.enforce_locks(update, context)
        if deleted:
            if msg.from_user:
                await punishments.process_violation(msg.chat_id, msg.from_user.id, msg.from_user.username, context)
            return

    # Global reply trigger
    await developer.trigger_global_reply(update, context)

    # Text command routing & keyword responses (all members, new messages only)
    if not is_edit and msg.text:
        await route_text_command(update, context)
        await trigger_keyword_response(update, context)

    # Edited message: also run through keyword/global triggers
    if is_edit and msg.text:
        await trigger_keyword_response(update, context)


async def combined_group_handler(update: Update, context):
    await _run_group_pipeline(update, context, is_edit=False)


async def edited_group_handler(update: Update, context):
    await _run_group_pipeline(update, context, is_edit=True)


async def pv_message_handler(update: Update, context):
    if not await maintenance_check(update, context):
        return
    msg = update.message
    if not msg or msg.chat.type != "private":
        return

    from modules.stats import track_pv_user
    await track_pv_user(update, context)

    ok = await subscriptions.check_pv_subscription(update, context)
    if not ok:
        return

    pv_locks = db.get_pv_lock_config()
    lock_map = {
        "photos": msg.photo, "stickers": msg.sticker,
        "files": msg.document, "videos": msg.video, "voice": msg.voice,
    }
    for key, field in lock_map.items():
        if pv_locks.get(key) and field:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    await developer.trigger_global_reply(update, context)

    if msg.from_user and (
        msg.from_user.id == DEVELOPER_ID or msg.from_user.id in db.get_secondary_devs()
    ):
        await developer.handle_dev_message(update, context)


async def new_members_handler(update: Update, context):
    await stats.handle_bot_join(update, context)
    await locks.handle_new_member(update, context)


async def service_messages_handler(update: Update, context):
    await media_filters.filter_notifications(update, context)


# ── Main ──────────────────────────────────────────────────
def main():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    app = Application.builder().token(BOT_TOKEN).build()

    # ── ConversationHandlers
    app.add_handler(get_whisper_conversation_handler(), group=0)
    app.add_handler(get_add_conversation_handler(), group=1)
    app.add_handler(get_edit_conversation_handler(), group=1)

    # ── Commands
    app.add_handler(CommandHandler("start", cmd_start), group=2)
    app.add_handler(CommandHandler("panel", developer.cmd_panel), group=2)
    app.add_handler(CommandHandler("users", developer.cmd_export_users), group=2)
    app.add_handler(CommandHandler("groups", developer.cmd_export_groups), group=2)

    # ── Callbacks: normalizer / PV
    app.add_handler(CallbackQueryHandler(callback_help, pattern="^help_"), group=3)
    app.add_handler(CallbackQueryHandler(callback_pv_menu, pattern="^pv_"), group=3)

    # Ranks
    app.add_handler(CallbackQueryHandler(ranks.callback_edit_perms, pattern=r"^editperms_\d+_\d+$"), group=3)
    app.add_handler(CallbackQueryHandler(ranks.callback_toggle_perm, pattern=r"^perm_\d+_"), group=3)
    app.add_handler(CallbackQueryHandler(ranks.callback_perms_back, pattern="^perms_back$"), group=3)

    # Media filters
    app.add_handler(CallbackQueryHandler(media_filters.callback_media_status, pattern="^media_status$"), group=3)
    app.add_handler(CallbackQueryHandler(media_filters.callback_media_edit, pattern="^media_edit$"), group=3)
    app.add_handler(CallbackQueryHandler(media_filters.callback_media_toggle, pattern="^media_toggle_"), group=3)
    app.add_handler(CallbackQueryHandler(media_filters.callback_media_back, pattern="^media_back$"), group=3)

    # Staff media panel
    app.add_handler(CallbackQueryHandler(callback_staff_media_toggle, pattern=r"^smedia_\d+_"), group=3)
    app.add_handler(CallbackQueryHandler(callback_staff_media_back, pattern="^smedia_back$"), group=3)

    # Locks
    app.add_handler(CallbackQueryHandler(locks.callback_lock_status, pattern="^lock_status$"), group=3)
    app.add_handler(CallbackQueryHandler(locks.callback_lock_edit, pattern="^lock_edit$"), group=3)
    app.add_handler(CallbackQueryHandler(locks.callback_lock_toggle, pattern="^lock_toggle_"), group=3)
    app.add_handler(CallbackQueryHandler(locks.callback_lock_back, pattern="^lock_back$"), group=3)

    # Punishments / auto-mute
    app.add_handler(CallbackQueryHandler(punishments.callback_automute_status, pattern="^automute_status$"), group=3)
    app.add_handler(CallbackQueryHandler(punishments.callback_automute_settings, pattern="^automute_settings$"), group=3)
    app.add_handler(CallbackQueryHandler(punishments.callback_automute_enable, pattern="^automute_enable$"), group=3)
    app.add_handler(CallbackQueryHandler(punishments.callback_automute_disable, pattern="^automute_disable$"), group=3)
    app.add_handler(CallbackQueryHandler(punishments.callback_automute_back, pattern="^automute_back$"), group=3)
    app.add_handler(CallbackQueryHandler(punishments.callback_unmute, pattern=r"^unmute_\d+$"), group=3)

    # Whisper
    app.add_handler(CallbackQueryHandler(callback_view_whisper, pattern=r"^whisper_[a-f0-9\-]+$"), group=3)

    # Developer panel
    app.add_handler(CallbackQueryHandler(developer.callback_dev, pattern="^dev_"), group=3)
    app.add_handler(CallbackQueryHandler(developer.callback_broadcast, pattern="^bcast_"), group=3)

    # YouTube
    app.add_handler(CallbackQueryHandler(callback_dl_audio, pattern=r"^dl_audio_"), group=3)
    app.add_handler(CallbackQueryHandler(callback_yt_back, pattern="^yt_search_back$"), group=3)

    # Games — Quiz
    app.add_handler(CallbackQueryHandler(callback_quiz, pattern=r"^quiz_(mcq|tf)_"), group=3)
    app.add_handler(CallbackQueryHandler(callback_quiz_done, pattern="^quiz_done$"), group=3)

    # Games — XO
    app.add_handler(CallbackQueryHandler(callback_xo_join, pattern=r"^xo_join_\d+$"), group=3)
    app.add_handler(CallbackQueryHandler(callback_xo_move, pattern=r"^xo_move_"), group=3)

    # Games — Math
    app.add_handler(CallbackQueryHandler(callback_math, pattern=r"^math_"), group=3)

    # Games — RPS
    app.add_handler(CallbackQueryHandler(callback_rps_join, pattern=r"^rps_join_\d+$"), group=3)
    app.add_handler(CallbackQueryHandler(callback_rps_pick, pattern=r"^rps_\d+_\d+_(حجر|ورقه|مقص)$"), group=3)

    # Games — Minefield
    app.add_handler(CallbackQueryHandler(callback_mine, pattern=r"^mine_"), group=3)

    # Games — Number Guessing
    app.add_handler(CallbackQueryHandler(callback_guess, pattern=r"^guess_"), group=3)

    # Games — enable/disable from dashboard
    async def _cb_games_enable(update, context):
        q = update.callback_query
        rank = await __import__('utils').get_user_rank(q.message.chat_id, q.from_user.id, context)
        if rank not in ("developer", "owner", "creator"):
            await q.answer("❖ للمدراء فقط.", show_alert=True); return
        db.groups_col.update_one({"group_id": q.message.chat_id}, {"$set": {"games_enabled": True}})
        await q.answer("✦ تم تفعيل الألعاب.")

    async def _cb_games_disable(update, context):
        q = update.callback_query
        rank = await __import__('utils').get_user_rank(q.message.chat_id, q.from_user.id, context)
        if rank not in ("developer", "owner", "creator"):
            await q.answer("❖ للمدراء فقط.", show_alert=True); return
        db.groups_col.update_one({"group_id": q.message.chat_id}, {"$set": {"games_enabled": False}})
        await q.answer("▼ تم تعطيل الألعاب.")

    app.add_handler(CallbackQueryHandler(_cb_games_enable, pattern="^games_enable_cb$"), group=3)
    app.add_handler(CallbackQueryHandler(_cb_games_disable, pattern="^games_disable_cb$"), group=3)

    # ── Group new messages
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.ALL & ~filters.COMMAND, combined_group_handler),
        group=4,
    )

    # ── Group edited messages — full pipeline
    app.add_handler(
        MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.ChatType.GROUPS, edited_group_handler),
        group=4,
    )

    # ── Service messages
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler),
        group=4,
    )
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER | filters.StatusUpdate.PINNED_MESSAGE,
            service_messages_handler,
        ),
        group=4,
    )

    # ── Private chat
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, pv_message_handler),
        group=5,
    )

    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
