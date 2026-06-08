from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank, rank_level, rank_badge, is_higher_rank
import database as db
from config import DEVELOPER_ID


PERM_KEYS = [
    ("change_info", "تغيير معلومات المجموعه"),
    ("delete_messages", "مسح الرسائل"),
    ("ban_users", "حظر مستخدمين"),
    ("pin_messages", "تثبيت الرسائل"),
    ("manage_calls", "التحكم في المكالمات"),
    ("edit_tags", "تعديل وسم الاعضاء"),
    ("add_admins", "اضافه مشرفين جدد"),
    ("invite_link", "دعوه مستخدمين"),
]

# ── Telegram permission matrices per rank ─────────────────
# Moderator: full except ban/promote/change_info/edit_tags
_MODERATOR_TG_PERMS = dict(
    can_delete_messages=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_manage_video_chats=True,
    can_manage_chat=True,
    can_restrict_members=False,
    can_change_info=False,
    can_promote_members=False,
)
# Admin: full except promote/change_info
_ADMIN_TG_PERMS = dict(
    can_delete_messages=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_manage_video_chats=True,
    can_manage_chat=True,
    can_restrict_members=True,
    can_change_info=False,
    can_promote_members=False,
)
# Creator: all on
_CREATOR_TG_PERMS = dict(
    can_delete_messages=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_manage_video_chats=True,
    can_manage_chat=True,
    can_restrict_members=True,
    can_change_info=True,
    can_promote_members=True,
)
# Strip all
_STRIP_TG_PERMS = dict(
    can_delete_messages=False,
    can_restrict_members=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_video_chats=False,
    can_manage_chat=False,
    can_change_info=False,
    can_promote_members=False,
)


def _rank_to_tg_perms(rank: str) -> dict:
    return {"creator": _CREATOR_TG_PERMS, "admin": _ADMIN_TG_PERMS}.get(rank, _MODERATOR_TG_PERMS)


def _perms_keyboard(group_id: int, target_id: int) -> object:
    perms = db.get_user_permissions(group_id, target_id)
    rows = []
    for i in range(0, len(PERM_KEYS), 2):
        row = []
        for key, label in PERM_KEYS[i : i + 2]:
            enabled = perms.get(key, False)
            style = "success" if enabled else "danger"
            state = "✦ مفعل" if enabled else "✦ معطل"
            row.append(btn(f"{label} ◈ {state}", f"perm_{target_id}_{key}", style=style))
        rows.append(row)
    rows.append([btn("◀ رجوع", "perms_back", style="danger")])
    return keyboard(rows)


async def _resolve_target(msg, context):
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.username, u.full_name
    if context.args:
        try:
            uid = int(context.args[0])
            try:
                cm = await context.bot.get_chat_member(msg.chat_id, uid)
                u = cm.user
                return u.id, u.username, u.full_name
            except Exception:
                return uid, None, str(uid)
        except ValueError:
            pass
    return None, None, None


async def _promote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_rank: str):
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)
    if rank_level(actor_rank) >= rank_level(target_rank):
        await msg.reply_text("<b>❖ لا تملك صلاحية ترقية بهذا المستوى.</b>", parse_mode=ParseMode.HTML)
        return

    target_id, target_username, target_name = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ يجب الرد على رسالة المستخدم أو إدخال معرفه الرقمي.</b>", parse_mode=ParseMode.HTML
        )
        return

    target_rank_current = await get_user_rank(chat_id, target_id, context)
    if not is_higher_rank(actor_rank, target_rank_current):
        await msg.reply_text(
            "<b>❖ لا يمكنك ترقية مستخدم برتبة مساوية أو أعلى.</b>", parse_mode=ParseMode.HTML
        )
        return

    tg_perms = _rank_to_tg_perms(target_rank)
    try:
        await context.bot.promote_chat_member(chat_id, target_id, **tg_perms)
    except Exception:
        pass

    db.set_user_rank(chat_id, target_id, target_rank, target_username)
    badge = rank_badge(target_rank)
    display = f"@{target_username}" if target_username else esc(target_name or str(target_id))

    text = (
        f"<b>❖ تمت الترقية</b>\n\n"
        f"<blockquote>"
        f"➔ المستخدم: <b>{display}</b>\n"
        f"➔ الرتبة الجديدة: <b>{badge}</b>\n"
        f"➔ بواسطة: <b>{esc(msg.from_user.full_name)}</b>"
        f"</blockquote>"
    )
    kb = keyboard([[btn("تعديل الصلاحيات", f"editperms_{msg.from_user.id}_{target_id}", style="primary")]])
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _demote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_rank: str):
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)

    target_id, target_username, target_name = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ يجب الرد على رسالة المستخدم أو إدخال معرفه الرقمي.</b>", parse_mode=ParseMode.HTML
        )
        return

    target_rank_current = await get_user_rank(chat_id, target_id, context)
    if not is_higher_rank(actor_rank, target_rank_current):
        await msg.reply_text("<b>❖ لا يمكنك تنزيل هذا المستخدم.</b>", parse_mode=ParseMode.HTML)
        return

    if target_rank_current != target_rank:
        await msg.reply_text(
            f"<b>◈ هذا المستخدم لا يحمل رتبة {rank_badge(target_rank)}.</b>", parse_mode=ParseMode.HTML
        )
        return

    try:
        await context.bot.promote_chat_member(chat_id, target_id, **_STRIP_TG_PERMS)
    except Exception:
        pass

    db.remove_user_rank(chat_id, target_id)
    display = f"@{target_username}" if target_username else esc(target_name or str(target_id))
    await msg.reply_text(
        f"<b>▼ تم التنزيل</b>\n\n"
        f"<blockquote>"
        f"➔ المستخدم: <b>{display}</b>\n"
        f"➔ الرتبة المُزالة: <b>{rank_badge(target_rank)}</b>"
        f"</blockquote>",
        parse_mode=ParseMode.HTML,
    )


# ── Promote/demote shorthands ─────────────────────────────

async def cmd_promote_creator(u, c): await _promote(u, c, "creator")
async def cmd_demote_creator(u, c): await _demote(u, c, "creator")
async def cmd_promote_admin(u, c): await _promote(u, c, "admin")
async def cmd_demote_admin(u, c): await _demote(u, c, "admin")
async def cmd_promote_moderator(u, c): await _promote(u, c, "moderator")
async def cmd_demote_moderator(u, c): await _demote(u, c, "moderator")


# ── Mass demotion commands ────────────────────────────────

async def cmd_mass_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنزيل الكل — clears all bot-registered staff in this group."""
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك فقط.</b>", parse_mode=ParseMode.HTML)
        return

    docs = list(db.users_col.find({"group_id": chat_id, "rank": {"$in": ["creator", "admin", "moderator"]}}))
    count = 0
    for doc in docs:
        try:
            await context.bot.promote_chat_member(chat_id, doc["user_id"], **_STRIP_TG_PERMS)
        except Exception:
            pass
        db.remove_user_rank(chat_id, doc["user_id"])
        count += 1

    await msg.reply_text(
        f"<b>▼ تم تنزيل الكل</b>\n\n<blockquote>➔ عدد المُنزَّلين: <b>{count}</b></blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_reset_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اعاده تعيين المجموعه — demotes ALL Telegram admins via API + clears bot DB."""
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner"):
        await msg.reply_text(
            "<b>❖ هذا الأمر للمالك فقط.</b>", parse_mode=ParseMode.HTML
        )
        return

    await msg.reply_text("<b>◈ جارٍ إعادة التعيين...</b>", parse_mode=ParseMode.HTML)

    api_demoted = 0
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for a in admins:
            if a.user.is_bot or a.status == "creator":
                continue
            try:
                await context.bot.promote_chat_member(chat_id, a.user.id, **_STRIP_TG_PERMS)
                api_demoted += 1
            except Exception:
                pass
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل جلب المشرفين: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)
        return

    # Clear bot DB
    db.users_col.update_many(
        {"group_id": chat_id, "rank": {"$in": ["creator", "admin", "moderator"]}},
        {"$unset": {"rank": ""}},
    )

    await msg.reply_text(
        f"<b>❖ إعادة التعيين مكتملة</b>\n\n"
        f"<blockquote>"
        f"➔ مُنزَّلون من Telegram API: <b>{api_demoted}</b>\n"
        f"➔ تم مسح سجلات البوت بالكامل."
        f"</blockquote>",
        parse_mode=ParseMode.HTML,
    )


# ── Audit command ─────────────────────────────────────────

async def cmd_audit_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)
    if actor_rank not in ("developer", "owner", "creator"):
        await msg.reply_text("<b>❖ هذا الأمر للمالك والمنشئ فقط.</b>", parse_mode=ParseMode.HTML)
        return

    await msg.reply_text("<b>◈ جاري فحص المجموعة...</b>", parse_mode=ParseMode.HTML)

    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)
        return

    creators_tg, admins_tg = [], []
    for a in admins:
        u = a.user
        if u.is_bot:
            continue
        if a.status == "creator":
            creators_tg.append(u)
            db.set_user_rank(chat_id, u.id, "owner", u.username)
        elif a.status == "administrator":
            admins_tg.append(u)
            existing = db.users_col.find_one({"group_id": chat_id, "user_id": u.id})
            if not existing or existing.get("rank") not in ("creator", "admin", "moderator"):
                db.set_user_rank(chat_id, u.id, "admin", u.username)

    custom_creators = list(db.users_col.find({"group_id": chat_id, "rank": "creator"}))
    custom_admins = list(db.users_col.find({"group_id": chat_id, "rank": "admin"}))
    custom_mods = list(db.users_col.find({"group_id": chat_id, "rank": "moderator"}))
    muted_count = db.muted_users_col.count_documents({"group_id": chat_id})
    banned_count = db.banned_users_col.count_documents({"group_id": chat_id})

    def _fmt(docs):
        return ", ".join(
            f"@{d['username']}" if d.get("username") else f"<code>{d['user_id']}</code>"
            for d in docs
        ) or "—"

    await msg.reply_text(
        "<b>❖ تقرير فحص المجموعة</b>\n\n"
        f"<blockquote>"
        f"➔ المنشئون (TG): <b>{len(creators_tg)}</b>\n"
        f"➔ الأدمنية (TG): <b>{len(admins_tg)}</b>\n\n"
        f"➔ منشئو البوت: <b>{len(custom_creators)}</b> — {_fmt(custom_creators)}\n"
        f"➔ أدمنية البوت: <b>{len(custom_admins)}</b> — {_fmt(custom_admins)}\n"
        f"➔ مشرفو البوت: <b>{len(custom_mods)}</b> — {_fmt(custom_mods)}\n\n"
        f"➔ المكتومون: <b>{muted_count}</b>\n"
        f"➔ المحظورون: <b>{banned_count}</b>"
        f"</blockquote>",
        parse_mode=ParseMode.HTML,
    )


# ── صلاحيات command ───────────────────────────────────────

async def cmd_check_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    actor_rank = await get_user_rank(chat_id, msg.from_user.id, context)

    target_id, target_username, target_name = await _resolve_target(msg, context)
    if not target_id:
        await msg.reply_text(
            "<b>◈ الاستخدام: صلاحيات (رداً على رسالة) أو صلاحيات [معرف]</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        cm = await context.bot.get_chat_member(chat_id, target_id)
    except Exception as e:
        await msg.reply_text(f"<b>◈ فشل: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)
        return

    display = f"@{target_username}" if target_username else esc(target_name or str(target_id))
    tg_perms = {
        "can_delete_messages": "مسح الرسائل",
        "can_restrict_members": "تقييد الأعضاء",
        "can_invite_users": "دعوة مستخدمين",
        "can_pin_messages": "تثبيت الرسائل",
        "can_manage_video_chats": "إدارة مكالمات الفيديو",
        "can_manage_chat": "إدارة المجموعة",
        "can_change_info": "تغيير المعلومات",
        "can_promote_members": "ترقية الأعضاء",
    }
    lines = [
        f"➔ <b>{label}:</b> {'✦ مفعل' if getattr(cm, key, False) else '○ معطل'}"
        for key, label in tg_perms.items()
    ]
    rank_lbl = rank_badge(await get_user_rank(chat_id, target_id, context))
    text = (
        f"<b>❖ صلاحيات: {display}</b>\n"
        f"<blockquote>➔ الرتبة: <b>{rank_lbl}</b></blockquote>\n\n"
        f"<blockquote>" + "\n".join(lines) + "</blockquote>"
    )
    rows = []
    target_rank = await get_user_rank(chat_id, target_id, context)
    if actor_rank in ("developer", "owner", "creator") and is_higher_rank(actor_rank, target_rank):
        rows.append([btn("تعديل صلاحيات البوت", f"editperms_{msg.from_user.id}_{target_id}", style="primary")])
    rows.append([btn("◀ رجوع", "perms_back", style="danger")])
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard(rows))


# ── Info commands ─────────────────────────────────────────

async def cmd_my_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    await msg.reply_text(
        f"<b>رتبتك هي:</b> <tg-spoiler>{esc(rank_badge(rank))}</tg-spoiler>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_my_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    perms = db.get_user_permissions(msg.chat_id, msg.from_user.id)
    lines = [
        f"➔ {label}: <b>{'✦ مفعل' if perms.get(key) else '✦ معطل'}</b>"
        for key, label in PERM_KEYS
    ]
    await msg.reply_text(
        "<b>❖ صلاحياتك الحالية:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_owner_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    try:
        admins = await context.bot.get_chat_administrators(msg.chat_id)
        owner = next((a for a in admins if a.status == "creator"), None)
        if not owner:
            await msg.reply_text("<b>◈ لم يتم العثور على المالك.</b>", parse_mode=ParseMode.HTML)
            return
        u = owner.user
        username = f"@{u.username}" if u.username else str(u.id)
        link = f"https://t.me/{u.username}" if u.username else f"tg://user?id={u.id}"
        await msg.reply_text(
            f"<b>✦ مالك المجموعة</b>\n\n"
            f"<blockquote>➔ الاسم: <b>{esc(u.full_name)}</b>\n➔ المعرف: <b>{esc(username)}</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("الملف الشخصي", url=link, style="primary")]]),
        )
    except Exception as e:
        await msg.reply_text(f"<b>◈ خطأ: {esc(str(e))}</b>", parse_mode=ParseMode.HTML)


async def _list_rank(update, context, rank, title):
    msg = update.message
    docs = list(db.users_col.find({"group_id": msg.chat_id, "rank": rank}))
    if not docs:
        await msg.reply_text(f"<b>◈ لا يوجد {title}.</b>", parse_mode=ParseMode.HTML)
        return
    lines = [
        f"{i}. <b>{'@'+d['username'] if d.get('username') else 'ID:'+str(d['user_id'])}</b>"
        for i, d in enumerate(docs, 1)
    ]
    await msg.reply_text(
        f"<b>❖ قائمة {title}:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_list_creators(u, c): await _list_rank(u, c, "creator", "المنشئين")
async def cmd_list_admins(u, c): await _list_rank(u, c, "admin", "الأدمنية")
async def cmd_list_moderators(u, c): await _list_rank(u, c, "moderator", "المشرفين")


async def cmd_all_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    sections = []
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        owner = next((a for a in admins if a.status == "creator"), None)
        if owner:
            u = owner.user
            sections.append(f"<b>✦ المالك:</b>\n➔ {'@'+u.username if u.username else str(u.id)}")
    except Exception:
        pass

    for rank, title, badge in [("creator", "المنشئون", "◈"), ("admin", "الأدمنية", "▲"), ("moderator", "المشرفون", "▼")]:
        docs = list(db.users_col.find({"group_id": chat_id, "rank": rank}))
        if docs:
            lines = [f"➔ @{d['username']}" if d.get("username") else f"➔ ID:{d['user_id']}" for d in docs]
            sections.append(f"<b>{badge} {title}:</b>\n" + "\n".join(lines))

    if not sections:
        await msg.reply_text("<b>◈ لا يوجد طاقم إداري مسجل.</b>", parse_mode=ParseMode.HTML)
        return
    await msg.reply_text(
        "<b>❖ المدراء والإدارة:</b>\n\n<blockquote>" + "\n\n".join(sections) + "</blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_set_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not context.args:
        await msg.reply_text("<b>◈ الاستخدام: لقب [اللقب المطلوب]</b>", parse_mode=ParseMode.HTML)
        return

    chat_id = msg.chat_id
    user_id = msg.from_user.id
    title = " ".join(context.args)

    # Re-promote trick: fetch current TG perms, re-promote to register bot as promoter
    tg_perms_applied = False
    try:
        cm = await context.bot.get_chat_member(chat_id, user_id)
        current_rank = await get_user_rank(chat_id, user_id, context)
        perms_dict = _rank_to_tg_perms(current_rank)
        await context.bot.promote_chat_member(chat_id, user_id, **perms_dict)
        tg_perms_applied = True
    except Exception:
        pass

    title_set = False
    if tg_perms_applied:
        try:
            await context.bot.set_chat_administrator_custom_title(chat_id, user_id, title)
            title_set = True
        except Exception:
            pass

    # Save in DB regardless
    db.users_col.update_one(
        {"group_id": chat_id, "user_id": user_id},
        {"$set": {"tag": title}}, upsert=True,
    )

    if title_set:
        note = ""
    else:
        note = "\n<blockquote>➔ ملاحظة: تم حفظ اللقب في قاعدة البيانات. لم يتم تطبيقه على Telegram بسبب قيود API.</blockquote>"

    await msg.reply_text(
        f"<b>✦ تم تعيين اللقب:</b>\n<blockquote>➔ {esc(title)}</blockquote>{note}",
        parse_mode=ParseMode.HTML,
    )


# ── Callbacks ─────────────────────────────────────────────

async def callback_edit_perms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    actor_id, target_id = int(parts[1]), int(parts[2])
    user_id = query.from_user.id
    if user_id != actor_id:
        actor_rank = await get_user_rank(query.message.chat_id, user_id, context)
        if actor_rank not in ("developer", "owner", "creator"):
            await query.answer("❖ ليس لديك صلاحية.", show_alert=True)
            return
    chat_id = query.message.chat_id
    target_doc = db.users_col.find_one({"group_id": chat_id, "user_id": target_id})
    name = target_doc.get("username", str(target_id)) if target_doc else str(target_id)
    await query.edit_message_text(
        f"<b>❖ تعديل صلاحيات:</b>\n<blockquote>➔ المستخدم: <b>{esc(name)}</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=_perms_keyboard(chat_id, target_id),
    )


async def callback_toggle_perm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    target_id, perm_key = int(parts[1]), parts[2]
    chat_id = query.message.chat_id
    perms = db.get_user_permissions(chat_id, target_id)
    perms[perm_key] = not perms.get(perm_key, False)
    db.set_user_permissions(chat_id, target_id, perms)

    # Sync custom perms to Telegram immediately
    try:
        tg_perms = {
            "can_change_info": perms.get("change_info", False),
            "can_delete_messages": perms.get("delete_messages", False),
            "can_restrict_members": perms.get("ban_users", False),
            "can_pin_messages": perms.get("pin_messages", False),
            "can_manage_video_chats": perms.get("manage_calls", False),
            "can_promote_members": perms.get("add_admins", False),
            "can_invite_users": perms.get("invite_link", True),
            "can_manage_chat": True,
        }
        await context.bot.promote_chat_member(chat_id, target_id, **tg_perms)
    except Exception:
        pass

    await query.edit_message_reply_markup(reply_markup=_perms_keyboard(chat_id, target_id))


async def callback_perms_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("<b>❖ تم الرجوع.</b>", parse_mode=ParseMode.HTML)
