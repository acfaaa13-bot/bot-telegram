from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank, rank_level, is_staff
import database as db

_ALL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=False,
    can_invite_users=True,
    can_pin_messages=False,
)


def _unmute_kb(user_id: int) -> object:
    return keyboard([[btn("فك الكتم", f"unmute_{user_id}", style="danger")]])


async def cmd_mass_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مسح N — delete last N messages (max 1000). Staff only."""
    import asyncio
    msg = update.message
    chat_id = msg.chat_id
    rank = await get_user_rank(chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator", "admin", "moderator"):
        return

    if not context.args:
        return
    try:
        count = min(int(context.args[0]), 1000)
    except ValueError:
        return

    # Delete the trigger message first
    try:
        await msg.delete()
    except Exception:
        pass

    deleted = 0
    # Walk message IDs backwards from current message
    start_id = msg.message_id - 1
    ids_to_delete = list(range(max(1, start_id - count + 1), start_id + 1))
    ids_to_delete.reverse()

    # Telegram allows deleting up to 100 messages per deleteMessages call
    for i in range(0, len(ids_to_delete), 100):
        batch = ids_to_delete[i : i + 100]
        try:
            await context.bot.delete_messages(chat_id, batch)
            deleted += len(batch)
        except Exception:
            # Fall back to one-by-one if bulk fails
            for mid in batch:
                try:
                    await context.bot.delete_message(chat_id, mid)
                    deleted += 1
                except Exception:
                    pass

    # Send confirmation and auto-delete after 5 seconds
    try:
        confirm = await context.bot.send_message(
            chat_id,
            f"<b>❖ تم مسح {deleted} رسالة بنجاح.</b>",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(5)
        await confirm.delete()
    except Exception:
        pass


async def _check_auto_mute(chat_id: int, user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE):
    group = db.get_group(chat_id)
    auto_mute = group.get("auto_mute", {})
    if not auto_mute.get("enabled", False):
        return
    warnings = db.add_warning(chat_id, user_id)
    max_warn = auto_mute.get("max_warnings", 3)
    duration = auto_mute.get("mute_duration", 10)
    name = f"@{username}" if username else str(user_id)

    if warnings >= max_warn:
        until = datetime.now() + timedelta(minutes=duration)
        try:
            await context.bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            db.register_muted(chat_id, user_id, username, timed=True, until=until)
        except Exception:
            pass
        db.reset_warnings(chat_id, user_id)
        await context.bot.send_message(
            chat_id,
            f"<b>▼ كتم تلقائي</b>\n\n"
            f"<blockquote>➔ المستخدم: <b>{esc(name)}</b>\n"
            f"➔ تم كتمه لمدة <b>{duration}</b> دقيقة بسبب تجاوز حد التحذيرات.</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=_unmute_kb(user_id),
        )
    else:
        await context.bot.send_message(
            chat_id,
            f"<b>◈ تحذير</b>\n\n"
            f"<blockquote>➔ المستخدم: <b>{esc(name)}</b>\n"
            f"➔ التحذيرات: <b>{warnings}/{max_warn}</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )


async def _resolve_target(msg, context):
    """Return (user_id, username, full_name, remaining_args) from reply or leading ID in args."""
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.username, u.full_name, list(context.args or [])
    if context.args:
        try:
            uid = int(context.args[0])
            remaining = list(context.args[1:])
            try:
                cm = await context.bot.get_chat_member(msg.chat_id, uid)
                u = cm.user
                return u.id, u.username, u.full_name, remaining
            except Exception:
                return uid, None, str(uid), remaining
        except ValueError:
            pass
    return None, None, None, []


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target_id, target_username, target_name, remaining = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ الاستخدام: كتم (رداً على رسالة) أو كتم [معرف] [مدة اختيارية]</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    target_rank = await get_user_rank(msg.chat_id, target_id, context)
    if rank_level(actor_rank) >= rank_level(target_rank):
        await msg.reply_text("<b>❖ لا يمكنك كتم هذا المستخدم.</b>", parse_mode=ParseMode.HTML)
        return

    duration_min = None
    if remaining:
        try:
            duration_min = int(remaining[0])
        except ValueError:
            pass

    display = f"@{target_username}" if target_username else esc(target_name or str(target_id))

    try:
        if duration_min:
            until = datetime.now() + timedelta(minutes=duration_min)
            await context.bot.restrict_chat_member(
                msg.chat_id, target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            db.register_muted(msg.chat_id, target_id, target_username, timed=True, until=until)
            text = (
                f"<b>▼ كتم مؤقت</b>\n\n"
                f"<blockquote>➔ المستخدم: <b>{display}</b>\n"
                f"➔ المدة: <b>{duration_min}</b> دقيقة</blockquote>"
            )
        else:
            await context.bot.restrict_chat_member(
                msg.chat_id, target_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            db.register_muted(msg.chat_id, target_id, target_username)
            text = (
                f"<b>▼ كتم دائم</b>\n\n"
                f"<blockquote>➔ المستخدم: <b>{display}</b></blockquote>"
            )
        await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_unmute_kb(target_id))
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل الكتم: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target_id, target_username, target_name, _ = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ الاستخدام: فك كتم (رداً على رسالة) أو فك كتم [معرف]</b>",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        await context.bot.restrict_chat_member(
            msg.chat_id, target_id, permissions=_ALL_PERMS
        )
        db.unregister_muted(msg.chat_id, target_id)
        display = f"@{target_username}" if target_username else esc(target_name or str(target_id))
        await msg.reply_text(
            f"<b>✦ فك الكتم</b>\n\n<blockquote>➔ <b>{display}</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل فك الكتم: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)


async def callback_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    actor_rank = await get_user_rank(chat_id, query.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator", "admin", "moderator"):
        await query.answer("❖ ليس لديك صلاحية فك الكتم.", show_alert=True)
        return
    await query.answer()
    try:
        target_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("❖ معرف غير صالح.", show_alert=True)
        return
    try:
        await context.bot.restrict_chat_member(chat_id, target_id, permissions=_ALL_PERMS)
        db.unregister_muted(chat_id, target_id)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            f"<b>✦ فك الكتم عن المعرف: <code>{target_id}</code></b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await query.answer(f"فشل: {str(e)[:100]}", show_alert=True)


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target_id, target_username, target_name, _ = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ الاستخدام: حظر (رداً على رسالة) أو حظر [معرف]</b>",
            parse_mode=ParseMode.HTML,
        )
        return
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    target_rank = await get_user_rank(msg.chat_id, target_id, context)
    if rank_level(actor_rank) >= rank_level(target_rank):
        await msg.reply_text("<b>❖ لا يمكنك حظر هذا المستخدم.</b>", parse_mode=ParseMode.HTML)
        return
    try:
        await context.bot.ban_chat_member(msg.chat_id, target_id)
        db.register_banned(msg.chat_id, target_id, target_username)
        display = f"@{target_username}" if target_username else esc(target_name or str(target_id))
        await msg.reply_text(
            f"<b>■ حظر</b>\n\n<blockquote>➔ <b>{display}</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل الحظر: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target_id, target_username, target_name, _ = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ الاستخدام: فك حظر (رداً على رسالة) أو فك حظر [معرف]</b>",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        await context.bot.unban_chat_member(msg.chat_id, target_id, only_if_banned=True)
        db.unregister_banned(msg.chat_id, target_id)
        display = f"@{target_username}" if target_username else esc(target_name or str(target_id))
        await msg.reply_text(
            f"<b>○ فك الحظر</b>\n\n<blockquote>➔ <b>{display}</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل فك الحظر: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)


async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("<b>◈ الرد على رسالة المستخدم مطلوب.</b>", parse_mode=ParseMode.HTML)
        return
    target = msg.reply_to_message.from_user
    if await is_staff(msg.chat_id, target.id, context):
        await msg.reply_text("<b>❖ لا يمكن تحذير مستخدم من الطاقم الإداري.</b>", parse_mode=ParseMode.HTML)
        return
    await _check_auto_mute(msg.chat_id, target.id, target.username, context)


async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("<b>◈ الرد على رسالة المستخدم مطلوب.</b>", parse_mode=ParseMode.HTML)
        return
    target = msg.reply_to_message.from_user
    new_val = db.decrement_warning(msg.chat_id, target.id)
    await msg.reply_text(
        f"<b>◈ تم مسح تحذير</b>\n\n"
        f"<blockquote>➔ <b>{esc(target.full_name)}</b>\n➔ التحذيرات المتبقية: <b>{new_val}</b></blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_set_warn_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        return
    if not context.args:
        await msg.reply_text("<b>◈ مثال: تعيين عدد التحذيرات 5</b>", parse_mode=ParseMode.HTML)
        return
    try:
        count = int(context.args[0])
    except ValueError:
        await msg.reply_text("<b>◈ يجب إدخال رقم صحيح.</b>", parse_mode=ParseMode.HTML)
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"auto_mute.max_warnings": count}})
    await msg.reply_text(f"<b>✦ تم تعيين حد التحذيرات: {count}</b>", parse_mode=ParseMode.HTML)


async def cmd_set_mute_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        return
    if not context.args:
        await msg.reply_text("<b>◈ مثال: تعيين مده الكتم 10</b>", parse_mode=ParseMode.HTML)
        return
    try:
        mins = int(context.args[0])
    except ValueError:
        await msg.reply_text("<b>◈ يجب إدخال رقم صحيح.</b>", parse_mode=ParseMode.HTML)
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"auto_mute.mute_duration": mins}})
    await msg.reply_text(
        f"<b>✦ تم تعيين مدة الكتم التلقائي: {mins} دقيقة</b>", parse_mode=ParseMode.HTML
    )


async def cmd_enable_auto_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"auto_mute.enabled": True}})
    await msg.reply_text("<b>✦ تم تفعيل الكتم التلقائي.</b>", parse_mode=ParseMode.HTML)


async def cmd_disable_auto_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"auto_mute.enabled": False}})
    await msg.reply_text("<b>▼ تم تعطيل الكتم التلقائي.</b>", parse_mode=ParseMode.HTML)


async def cmd_auto_mute_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    group = db.get_group(msg.chat_id)
    am = group.get("auto_mute", {})
    enabled = am.get("enabled", False)
    max_w = am.get("max_warnings", 3)
    dur = am.get("mute_duration", 10)
    status_lbl = "✦ مفعل" if enabled else "▼ معطل"
    text = (
        "<b>❖ نظام الكتم التلقائي</b>\n\n"
        f"<blockquote>"
        f"➔ الحالة: <b>{status_lbl}</b>\n"
        f"➔ حد التحذيرات: <b>{max_w}</b>\n"
        f"➔ مدة الكتم: <b>{dur} دقيقة</b>\n\n"
        f"➔ لتعيين الحد: <b>تعيين عدد التحذيرات [رقم]</b>\n"
        f"➔ لتعيين المدة: <b>تعيين مده الكتم [دقائق]</b>"
        f"</blockquote>"
    )
    kb = keyboard([
        [
            btn("تفعيل ✦", "automute_enable", style="success"),
            btn("▼ تعطيل", "automute_disable", style="danger"),
        ],
        [btn("◀ رجوع", "automute_back", style="danger")],
    ])
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def callback_automute_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = db.get_group(query.message.chat_id)
    am = group.get("auto_mute", {})
    enabled = "مفعل" if am.get("enabled") else "معطل"
    text = (
        f"<b>❖ حالة الكتم التلقائي:</b>\n\n"
        f"<blockquote>➔ الحالة: <b>{enabled}</b>\n"
        f"➔ حد التحذيرات: <b>{am.get('max_warnings', 3)}</b>\n"
        f"➔ مدة الكتم: <b>{am.get('mute_duration', 10)} دقيقة</b></blockquote>"
    )
    kb = keyboard([[btn("◀ رجوع", "automute_back", style="danger")]])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def callback_automute_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rank = await get_user_rank(query.message.chat_id, query.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ هذه القائمة للمالك والمنشئ فقط.", show_alert=True)
        return
    await query.answer()
    am = db.get_group(query.message.chat_id).get("auto_mute", {})
    enabled = am.get("enabled", False)
    text = (
        "<b>❖ إعدادات الكتم التلقائي:</b>\n\n"
        "<blockquote>"
        "➔ لتعيين عدد التحذيرات: <b>تعيين عدد التحذيرات [رقم]</b>\n"
        "➔ لتعيين مدة الكتم: <b>تعيين مده الكتم [دقائق]</b>"
        "</blockquote>"
    )
    kb = keyboard([
        [
            btn("تفعيل ✦" if not enabled else "✦ مفعل", "automute_enable", style="success"),
            btn("▼ تعطيل" if enabled else "معطل", "automute_disable", style="danger"),
        ],
        [btn("◀ رجوع", "automute_back", style="danger")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def callback_automute_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rank = await get_user_rank(query.message.chat_id, query.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ ليس لديك صلاحية.", show_alert=True)
        return
    await query.answer()
    db.groups_col.update_one({"group_id": query.message.chat_id}, {"$set": {"auto_mute.enabled": True}})
    await callback_automute_settings(update, context)


async def callback_automute_disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rank = await get_user_rank(query.message.chat_id, query.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        await query.answer("❖ ليس لديك صلاحية.", show_alert=True)
        return
    await query.answer()
    db.groups_col.update_one({"group_id": query.message.chat_id}, {"$set": {"auto_mute.enabled": False}})
    await callback_automute_settings(update, context)


async def callback_automute_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group = db.get_group(query.message.chat_id)
    am = group.get("auto_mute", {})
    enabled = am.get("enabled", False)
    status_lbl = "✦ مفعل" if enabled else "▼ معطل"
    text = (
        "<b>❖ نظام الكتم التلقائي</b>\n\n"
        f"<blockquote>"
        f"➔ الحالة: <b>{status_lbl}</b>\n"
        f"➔ حد التحذيرات: <b>{am.get('max_warnings', 3)}</b>\n"
        f"➔ مدة الكتم: <b>{am.get('mute_duration', 10)} دقيقة</b>"
        f"</blockquote>"
    )
    kb = keyboard([
        [
            btn("تفعيل ✦", "automute_enable", style="success"),
            btn("▼ تعطيل", "automute_disable", style="danger"),
        ],
        [btn("◀ رجوع", "automute_back", style="danger")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cmd_list_muted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    docs = list(db.muted_users_col.find({"group_id": msg.chat_id}))
    if not docs:
        await msg.reply_text("<b>◈ لا يوجد مكتومون حالياً.</b>", parse_mode=ParseMode.HTML)
        return
    lines = [
        f"{i}. <b>@{d['username']}</b>" if d.get("username") else f"{i}. <code>{d['user_id']}</code>"
        for i, d in enumerate(docs, 1)
    ]
    await msg.reply_text(
        "<b>❖ المكتومون:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_list_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    docs = list(db.banned_users_col.find({"group_id": msg.chat_id}))
    if not docs:
        await msg.reply_text("<b>◈ لا يوجد محظورون حالياً.</b>", parse_mode=ParseMode.HTML)
        return
    lines = [
        f"{i}. <b>@{d['username']}</b>" if d.get("username") else f"{i}. <code>{d['user_id']}</code>"
        for i, d in enumerate(docs, 1)
    ]
    await msg.reply_text(
        "<b>❖ المحظورون:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_bulk_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        return
    docs = list(db.muted_users_col.find({"group_id": msg.chat_id}))
    count = 0
    for doc in docs:
        try:
            await context.bot.restrict_chat_member(
                msg.chat_id, doc["user_id"], permissions=_ALL_PERMS
            )
            count += 1
        except Exception:
            pass
        db.unregister_muted(msg.chat_id, doc["user_id"])
    await msg.reply_text(
        f"<b>✦ تم فك كتم {count} مستخدم.</b>", parse_mode=ParseMode.HTML
    )


async def cmd_bulk_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor_rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        return
    docs = list(db.banned_users_col.find({"group_id": msg.chat_id}))
    count = 0
    for doc in docs:
        try:
            await context.bot.unban_chat_member(msg.chat_id, doc["user_id"], only_if_banned=True)
            count += 1
        except Exception:
            pass
        db.unregister_banned(msg.chat_id, doc["user_id"])
    await msg.reply_text(
        f"<b>✦ تم فك حظر {count} مستخدم.</b>", parse_mode=ParseMode.HTML
    )


async def process_violation(chat_id: int, user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE):
    await _check_auto_mute(chat_id, user_id, username, context)
