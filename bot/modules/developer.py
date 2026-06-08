import random
import io
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard
from config import DEVELOPER_ID
import database as db


def _is_any_dev(user_id: int) -> bool:
    return user_id == DEVELOPER_ID or user_id in db.get_secondary_devs()


def _is_primary_dev(user_id: int) -> bool:
    return user_id == DEVELOPER_ID


def _dev_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not _is_any_dev(user.id):
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


def _resolve_channel_ref(ref: str):
    ref = ref.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if ref.startswith(prefix):
            part = ref[len(prefix):].split("/")[0]
            return f"@{part}" if part != "c" else ref
    if ref.lstrip("-").isdigit():
        return int(ref)
    return ref if ref.startswith("@") else f"@{ref}"


def _panel_text(user_id: int) -> str:
    status = db.get_bot_status()
    dev_ch = db.get_developer_channel()
    profile = db.get_dev_profile()
    dev_sub = db.get_dev_sub()
    channel_set = "✦ محدد" if dev_ch.get("channel_id") else "○ غير محدد"
    uname_set = f"@{profile['username']}" if profile.get("username") else "○ غير محدد"
    src_set = profile.get("source_channel", "○ غير محدد")
    status_label = "✦ يعمل" if status else "▼ صيانة"
    sub_state = "✦ مفعل" if dev_sub.get("enabled") else "○ معطل"
    sub_target = {"groups": "المجموعات", "pv": "الخاص", "both": "الكل"}.get(dev_sub.get("target", "both"), "الكل")
    is_primary = _is_primary_dev(user_id)
    secondary_devs_count = len(db.get_secondary_devs())
    return (
        "<b>❖ لوحة المطور</b>\n\n"
        f"<blockquote>"
        f"➔ حالة البوت: <b>{status_label}</b>\n"
        + (f"➔ يوزر المطور: <b>{esc(uname_set)}</b>\n"
           f"➔ قناة السورس: <b>{esc(src_set)}</b>\n"
           f"➔ قناة الاشتراك (قديم): <b>{channel_set}</b>\n"
           f"➔ اشتراك المطور: <b>{sub_state}</b> ← <b>{sub_target}</b>\n"
           f"➔ المطورين الثانويون: <b>{secondary_devs_count}</b>"
           if is_primary else
           f"➔ وصول ثانوي — الإعدادات الرئيسية محجوبة.")
        + "</blockquote>"
    )


def _panel_kb(user_id: int) -> object:
    is_primary = _is_primary_dev(user_id)
    rows = [
        [btn("تشغيل البوت", "dev_bot_on", style="success"), btn("إيقاف البوت", "dev_bot_off", style="danger")],
        [btn("إذاعة للمجموعات", "dev_broadcast_groups", style="primary")],
        [btn("إذاعة الخاص", "dev_broadcast_pv", style="primary")],
    ]
    if is_primary:
        rows += [
            [btn("تعيين الاشتراك الإجباري", "dev_sub_menu", style="primary")],
            [btn("تعيين يوزر المطور", "dev_set_username", style="primary"),
             btn("تعيين قناة السورس", "dev_set_source", style="primary")],
            [btn("إضافة مطور", "dev_add_dev", style="success"),
             btn("حذف مطور", "dev_del_dev", style="danger"),
             btn("قائمة المطورين", "dev_list_devs", style="primary")],
        ]
    rows += [
        [btn("قفل وسائط الخاص", "dev_pv_locks", style="primary")],
        [btn("الردود العامة", "dev_global_replies", style="primary")],
    ]
    return keyboard(rows)


def _sub_menu_kb() -> object:
    dev_sub = db.get_dev_sub()
    enabled = dev_sub.get("enabled", False)
    target = dev_sub.get("target", "both")
    ch_set = "✦ محددة" if dev_sub.get("channel_id") else "○ غير محددة"
    return keyboard([
        [btn("الهدف: المجموعات", "dev_sub_target_groups", style="success" if target == "groups" else "primary"),
         btn("الهدف: الخاص", "dev_sub_target_pv", style="success" if target == "pv" else "primary"),
         btn("الهدف: الكل", "dev_sub_target_both", style="success" if target == "both" else "primary")],
        [btn("تفعيل ✦" if not enabled else "✦ مفعل", "dev_sub_on", style="success"),
         btn("▼ تعطيل", "dev_sub_off", style="danger")],
        [btn(f"تعيين قناة الاشتراك ({ch_set})", "dev_sub_set_channel", style="primary")],
        [btn("◀ رجوع", "dev_back", style="danger")],
    ])


@_dev_only
async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.effective_message
    user_id = (update.effective_user or update.message.from_user).id
    await msg.reply_text(_panel_text(user_id), parse_mode=ParseMode.HTML, reply_markup=_panel_kb(user_id))


async def callback_dev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not _is_any_dev(user_id):
        await query.answer("❖ غير مصرح.", show_alert=True)
        return
    await query.answer()
    data = query.data
    is_primary = _is_primary_dev(user_id)

    # Actions restricted to primary dev
    _primary_only = {
        "dev_sub_menu", "dev_sub_on", "dev_sub_off", "dev_sub_set_channel",
        "dev_sub_target_groups", "dev_sub_target_pv", "dev_sub_target_both",
        "dev_set_username", "dev_set_source",
        "dev_add_dev", "dev_del_dev",
    }
    if data in _primary_only and not is_primary:
        await query.answer("❖ هذا الإجراء للمطور الرئيسي فقط.", show_alert=True)
        return

    if data == "dev_bot_on":
        db.set_bot_status(True)
        await query.edit_message_text("<b>✦ تم تشغيل البوت.</b>", parse_mode=ParseMode.HTML)

    elif data == "dev_bot_off":
        db.set_bot_status(False)
        await query.edit_message_text("<b>▼ البوت في وضع الصيانة.</b>", parse_mode=ParseMode.HTML)

    elif data in ("dev_broadcast_groups", "dev_broadcast_pv"):
        context.user_data["broadcast_target"] = "groups" if data == "dev_broadcast_groups" else "pv"
        context.user_data["awaiting_broadcast"] = True
        label = "المجموعات" if data == "dev_broadcast_groups" else "الخاص"
        await query.edit_message_text(
            f"<b>❖ إذاعة لـ {label}</b>\n\n<blockquote>➔ أرسل الرسالة المراد إذاعتها:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("إلغاء", "dev_cancel_broadcast", style="danger")]]),
        )

    elif data == "dev_cancel_broadcast":
        context.user_data.pop("awaiting_broadcast", None)
        await query.edit_message_text("<b>◈ تم إلغاء الإذاعة.</b>", parse_mode=ParseMode.HTML)

    elif data == "dev_sub_menu":
        dev_sub = db.get_dev_sub()
        enabled = "✦ مفعل" if dev_sub.get("enabled") else "▼ معطل"
        target_map = {"groups": "المجموعات", "pv": "الخاص", "both": "الكل"}
        target = target_map.get(dev_sub.get("target", "both"), "الكل")
        ch_title = "✦ محددة" if dev_sub.get("channel_id") else "○ غير محددة"
        await query.edit_message_text(
            "<b>❖ إعدادات الاشتراك الإجباري</b>\n\n"
            f"<blockquote>➔ الحالة: <b>{enabled}</b>\n"
            f"➔ الهدف: <b>{target}</b>\n"
            f"➔ القناة: <b>{ch_title}</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=_sub_menu_kb(),
        )

    elif data == "dev_sub_on":
        db.set_dev_sub_state(True)
        await query.edit_message_reply_markup(reply_markup=_sub_menu_kb())

    elif data == "dev_sub_off":
        db.set_dev_sub_state(False)
        await query.edit_message_reply_markup(reply_markup=_sub_menu_kb())

    elif data in ("dev_sub_target_groups", "dev_sub_target_pv", "dev_sub_target_both"):
        db.set_dev_sub_target(data.replace("dev_sub_target_", ""))
        await query.edit_message_reply_markup(reply_markup=_sub_menu_kb())

    elif data == "dev_sub_set_channel":
        context.user_data["awaiting_dev_sub_channel"] = True
        await query.edit_message_text(
            "<b>❖ تعيين قناة اشتراك المطور</b>\n\n<blockquote>➔ أرسل @يوزر القناة أو رابطها:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_set_username":
        context.user_data["awaiting_dev_username"] = True
        await query.edit_message_text(
            "<b>❖ تعيين يوزر المطور</b>\n\n<blockquote>➔ أرسل @يوزر المطور:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_set_source":
        context.user_data["awaiting_source_channel"] = True
        await query.edit_message_text(
            "<b>❖ تعيين قناة السورس</b>\n\n<blockquote>➔ أرسل رابط القناة أو @يوزرها:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_add_dev":
        context.user_data["awaiting_add_dev"] = True
        await query.edit_message_text(
            "<b>❖ إضافة مطور ثانوي</b>\n\n<blockquote>➔ أرسل المعرف الرقمي للمستخدم:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_del_dev":
        context.user_data["awaiting_del_dev"] = True
        await query.edit_message_text(
            "<b>❖ حذف مطور ثانوي</b>\n\n<blockquote>➔ أرسل المعرف الرقمي للمستخدم:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_list_devs":
        devs = db.get_secondary_devs()
        if not devs:
            await query.answer("❖ لا يوجد مطورون ثانويون.", show_alert=True)
            return
        lines = [f"{i}. <code>{uid}</code>" for i, uid in enumerate(devs, 1)]
        await query.edit_message_text(
            "<b>❖ المطورون الثانويون:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_pv_locks":
        await _show_pv_locks(query, context)

    elif data.startswith("dev_pvlock_"):
        key = data.replace("dev_pvlock_", "")
        locks = db.get_pv_lock_config()
        locks[key] = not locks.get(key, False)
        db.set_pv_lock_config(locks)
        await _show_pv_locks(query, context)

    elif data == "dev_global_replies":
        await query.edit_message_text(
            "<b>❖ الردود العامة</b>\n\n"
            "<blockquote>"
            "➔ تعمل في جميع المجموعات والخاص.\n"
            "➔ إضافة رد: أرسل <b>رد عام [كلمة]</b>\n"
            "➔ حذف رد: أرسل <b>حذف رد عام [كلمة]</b>"
            "</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("◀ رجوع", "dev_back", style="danger")]]),
        )

    elif data == "dev_back":
        _clear_awaiting(context)
        await query.edit_message_text(
            _panel_text(user_id), parse_mode=ParseMode.HTML, reply_markup=_panel_kb(user_id)
        )


def _clear_awaiting(context):
    for key in (
        "awaiting_broadcast", "broadcast_target", "awaiting_dev_sub_channel",
        "awaiting_dev_username", "awaiting_source_channel", "awaiting_global_reply",
        "global_reply_keyword", "awaiting_add_dev", "awaiting_del_dev",
    ):
        context.user_data.pop(key, None)


async def _show_pv_locks(query, context):
    locks = db.get_pv_lock_config()
    lock_keys = [
        ("photos", "الصور"), ("stickers", "الملصقات"), ("files", "الملفات"),
        ("videos", "الفيديو"), ("voice", "الرسائل الصوتية"), ("editing", "التعديل"),
    ]
    rows = []
    for i in range(0, len(lock_keys), 2):
        row = []
        for key, label in lock_keys[i : i + 2]:
            locked = locks.get(key, False)
            row.append(btn(
                f"{label} ◈ {'قفل' if locked else 'فتح'}",
                f"dev_pvlock_{key}",
                style="danger" if locked else "success",
            ))
        rows.append(row)
    rows.append([btn("◀ رجوع", "dev_back", style="danger")])
    await query.edit_message_text("<b>❖ قفل وسائط الخاص:</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=keyboard(rows))


@_dev_only
async def handle_dev_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    user_id = msg.from_user.id
    is_primary = _is_primary_dev(user_id)

    if context.user_data.get("awaiting_broadcast"):
        context.user_data.pop("awaiting_broadcast", None)
        target = context.user_data.pop("broadcast_target", "groups")
        context.user_data.update(broadcast_msg_id=msg.message_id,
                                  broadcast_chat_id=msg.chat_id,
                                  broadcast_target_final=target,
                                  bcast_pin=False)
        await msg.reply_text(
            "<b>❖ تأكيد الإذاعة</b>\n\n<blockquote>➔ اختر خيارات الإرسال:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([
                [btn("تثبيت الرسالة", "bcast_pin", style="primary")],
                [btn("إبدأ الإرسال", "bcast_send", style="success")],
            ]),
        )
        return

    if is_primary and context.user_data.get("awaiting_dev_sub_channel"):
        context.user_data.pop("awaiting_dev_sub_channel", None)
        ref = (msg.text or "").strip()
        if ref:
            try:
                resolved = _resolve_channel_ref(ref)
                chat = await context.bot.get_chat(resolved)
                link = f"https://t.me/{chat.username}" if chat.username else ref
                dev_sub = db.get_dev_sub()
                db.set_dev_sub(chat.id, link, target=dev_sub.get("target", "both"),
                               enabled=dev_sub.get("enabled", True))
                await msg.reply_text(
                    f"<b>✦ تم تعيين قناة اشتراك المطور:</b>\n<blockquote>➔ {esc(chat.title)}</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                await msg.reply_text(f"<b>◈ فشل: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)
        return

    if is_primary and context.user_data.get("awaiting_dev_username"):
        context.user_data.pop("awaiting_dev_username", None)
        username = (msg.text or "").strip().lstrip("@")
        if username:
            db.set_dev_username(username)
            await msg.reply_text(f"<b>✦ تم تعيين يوزر المطور: @{esc(username)}</b>", parse_mode=ParseMode.HTML)
        return

    if is_primary and context.user_data.get("awaiting_source_channel"):
        context.user_data.pop("awaiting_source_channel", None)
        link = (msg.text or "").strip()
        if link:
            db.set_source_channel(link)
            await msg.reply_text(f"<b>✦ تم تعيين قناة السورس: {esc(link)}</b>", parse_mode=ParseMode.HTML)
        return

    if is_primary and context.user_data.get("awaiting_add_dev"):
        context.user_data.pop("awaiting_add_dev", None)
        try:
            uid = int((msg.text or "").strip())
            db.add_secondary_dev(uid)
            await msg.reply_text(f"<b>✦ تمت إضافة المطور الثانوي: <code>{uid}</code></b>", parse_mode=ParseMode.HTML)
        except ValueError:
            await msg.reply_text("<b>◈ يجب إدخال معرف رقمي صحيح.</b>", parse_mode=ParseMode.HTML)
        return

    if is_primary and context.user_data.get("awaiting_del_dev"):
        context.user_data.pop("awaiting_del_dev", None)
        try:
            uid = int((msg.text or "").strip())
            db.remove_secondary_dev(uid)
            await msg.reply_text(f"<b>✦ تم حذف المطور الثانوي: <code>{uid}</code></b>", parse_mode=ParseMode.HTML)
        except ValueError:
            await msg.reply_text("<b>◈ يجب إدخال معرف رقمي صحيح.</b>", parse_mode=ParseMode.HTML)
        return

    if context.user_data.get("awaiting_global_reply"):
        context.user_data.pop("awaiting_global_reply", None)
        keyword = context.user_data.pop("global_reply_keyword", "")
        if msg.photo:
            rt, content, caption = "photo", msg.photo[-1].file_id, msg.caption or ""
        elif msg.sticker:
            rt, content, caption = "sticker", msg.sticker.file_id, ""
        elif msg.text:
            rt, content, caption = "text", msg.text, ""
        else:
            await msg.reply_text("<b>◈ نوع غير مدعوم.</b>", parse_mode=ParseMode.HTML)
            return
        db.global_replies_col.insert_one({"keyword": keyword, "reply_type": rt, "content": content, "caption": caption})
        await msg.reply_text(
            f"<b>✦ تمت الإضافة للكلمة:</b> <code>{esc(keyword)}</code>", parse_mode=ParseMode.HTML
        )
        return

    if msg.text:
        raw = msg.text.strip()
        if raw.startswith("رد عام "):
            keyword = raw[len("رد عام "):].strip().lower()
            if keyword:
                context.user_data["global_reply_keyword"] = keyword
                context.user_data["awaiting_global_reply"] = True
                await msg.reply_text(
                    f"<b>❖ رد عام للكلمة:</b> <code>{esc(keyword)}</code>\n\n"
                    "<blockquote>➔ أرسل الرد (نص، صورة، أو ملصق):</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            return
        if raw.startswith("حذف رد عام "):
            keyword = raw[len("حذف رد عام "):].strip().lower()
            result = db.global_replies_col.delete_many({"keyword": keyword})
            await msg.reply_text(
                f"<b>✦ حُذفت {result.deleted_count} استجابة للكلمة:</b> <code>{esc(keyword)}</code>",
                parse_mode=ParseMode.HTML,
            )


async def callback_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _is_any_dev(query.from_user.id):
        await query.answer("❖ غير مصرح.", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "bcast_pin":
        context.user_data["bcast_pin"] = not context.user_data.get("bcast_pin", False)
        pin = context.user_data["bcast_pin"]
        await query.edit_message_reply_markup(reply_markup=keyboard([
            [btn("✦ تثبيت" if pin else "تثبيت", "bcast_pin", style="success" if pin else "primary")],
            [btn("إبدأ الإرسال", "bcast_send", style="success")],
        ]))

    elif data == "bcast_send":
        target = context.user_data.get("broadcast_target_final", "groups")
        source_chat = context.user_data.get("broadcast_chat_id")
        source_msg_id = context.user_data.get("broadcast_msg_id")
        pin = context.user_data.get("bcast_pin", False)

        chats = (
            [d["group_id"] for d in db.groups_col.find({}, {"group_id": 1})]
            if target == "groups"
            else [d["user_id"] for d in db.pv_users_col.find({}, {"user_id": 1})]
        )
        sent = failed = 0
        for chat_id in chats:
            try:
                fwd = await context.bot.forward_message(chat_id, source_chat, source_msg_id)
                if pin:
                    try:
                        await context.bot.pin_chat_message(chat_id, fwd.message_id)
                    except Exception:
                        pass
                sent += 1
            except Exception:
                failed += 1

        await query.edit_message_text(
            f"<b>✦ انتهت الإذاعة</b>\n\n"
            f"<blockquote>➔ أُرسل: <b>{sent}</b>\n➔ فشل: <b>{failed}</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )


@_dev_only
async def cmd_export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    users = list(db.pv_users_col.find({}))
    lines = [f"{'رقم':<6} {'الاسم':<25} {'المعرف':<20} {'ID':<15}", "-" * 70]
    for i, u in enumerate(users, 1):
        name = (u.get("name") or "")[:24]
        username = f"@{u['username']}" if u.get("username") else "-"
        lines.append(f"{i:<6} {name:<25} {username:<20} {u['user_id']:<15}")
    buf = io.BytesIO("\n".join(lines).encode("utf-8"))
    buf.name = "users.txt"
    await context.bot.send_document(msg.chat_id, document=buf, filename="users.txt")


@_dev_only
async def cmd_export_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    groups = list(db.groups_col.find({}))
    lines = [f"{'رقم':<6} {'الاسم':<30} {'الرابط':<35} {'ID':<15}", "-" * 90]
    for i, g in enumerate(groups, 1):
        name = (g.get("title") or "")[:29]
        link = (g.get("invite_link") or "-")[:34]
        lines.append(f"{i:<6} {name:<30} {link:<35} {g['group_id']:<15}")
    buf = io.BytesIO("\n".join(lines).encode("utf-8"))
    buf.name = "groups.txt"
    await context.bot.send_document(msg.chat_id, document=buf, filename="groups.txt")


async def trigger_global_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    keyword = msg.text.strip().lower()
    docs = list(db.global_replies_col.find({"keyword": keyword}))
    if not docs:
        return
    doc = random.choice(docs)
    try:
        if doc["reply_type"] == "text":
            await msg.reply_html(doc["content"])
        elif doc["reply_type"] == "photo":
            await context.bot.send_photo(
                msg.chat_id, photo=doc["content"],
                caption=doc.get("caption", ""), parse_mode=ParseMode.HTML,
                reply_to_message_id=msg.message_id,
            )
        elif doc["reply_type"] == "sticker":
            await context.bot.send_sticker(
                msg.chat_id, sticker=doc["content"],
                reply_to_message_id=msg.message_id,
            )
    except Exception:
        pass
