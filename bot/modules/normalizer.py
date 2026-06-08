import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, normalize_arabic, get_user_rank
from config import DEVELOPER_ID
import database as db


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    if context.args and context.args[0].startswith("whisper_"):
        return
    if msg.chat.type == "private":
        from modules.stats import track_pv_user
        await track_pv_user(update, context)
        await _show_pv_main(msg)
    else:
        await msg.reply_text(
            "<b>❖ مرحباً</b>\n\n"
            "<blockquote>➔ اكتب <b>اوامر</b> لعرض القائمة الرئيسية.</blockquote>",
            parse_mode=ParseMode.HTML,
        )


async def _show_pv_main(msg):
    profile = db.get_dev_profile()
    src = profile.get("source_channel", "")
    text = (
        "<b>❖ مرحباً بك</b>\n\n"
        "<blockquote>"
        "➔ هذا البوت نظام متكامل لإدارة المجموعات.\n"
        "➔ اختر أحد الخيارات أدناه:"
        "</blockquote>"
    )
    kb_rows = [[btn("ملف المطور", "pv_dev_profile", style="primary")]]
    if src:
        kb_rows[0].append(btn("قناة السورس", url=src, style="primary"))
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard(kb_rows))


async def callback_pv_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "pv_dev_profile":
        profile = db.get_dev_profile()
        username = profile.get("username", "")
        source = profile.get("source_channel", "")
        if not username:
            await query.answer("❖ لم يتم تعيين ملف المطور بعد.", show_alert=True)
            return
        link = f"https://t.me/{username}"
        kb_rows = [[btn("➔ تواصل مع المطور", url=link, style="primary")]]
        if source:
            kb_rows.append([btn("قناة السورس", url=source, style="primary")])
        kb_rows.append([btn("◀ رجوع", "pv_back", style="danger")])
        await query.edit_message_text(
            f"<b>❖ ملف المطور</b>\n\n<blockquote>➔ المطور: <b>@{esc(username)}</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(kb_rows),
        )

    elif data == "pv_back":
        profile = db.get_dev_profile()
        src = profile.get("source_channel", "")
        kb_rows = [[btn("ملف المطور", "pv_dev_profile", style="primary")]]
        if src:
            kb_rows[0].append(btn("قناة السورس", url=src, style="primary"))
        await query.edit_message_text(
            "<b>❖ مرحباً بك</b>\n\n"
            "<blockquote>"
            "➔ هذا البوت نظام متكامل لإدارة المجموعات.\n"
            "➔ اختر أحد الخيارات أدناه:"
            "</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(kb_rows),
        )


async def cmd_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await msg.reply_text(
        "<b>❖ لوحة الأوامر</b>\n\n<blockquote>اختر القسم المطلوب:</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(_MAIN_MENU_ROWS),
    )


_MAIN_MENU_ROWS = [
    [btn("◈ قسم الرتب", "help_ranks", style="primary"), btn("▲ قسم الحماية", "help_locks", style="primary")],
    [btn("■ قسم الوسائط", "help_media", style="primary"), btn("▼ قسم الكتم والحظر", "help_punish", style="primary")],
    [btn("➔ الردود التلقائية", "help_keywords", style="primary"), btn("❖ الاشتراك الثانوي", "help_sub", style="primary")],
    [btn("◈ الإحصائيات", "help_stats", style="primary")],
    [btn("❖ الألعاب والميوزك ❖", "help_games", style="primary")],
]


async def callback_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    back = keyboard([[btn("◀ رجوع", "help_back", style="danger")]])

    texts = {
        "help_ranks": (
            "<b>◈ قسم الرتب</b>\n\n<blockquote>"
            "➔ رفع منشئ / تنزيل منشئ\n"
            "➔ رفع ادمن / تنزيل ادمن\n"
            "➔ رفع مشرف / تنزيل مشرف\n"
            "➔ تنزيل الكل — تنزيل جميع الطاقم\n"
            "➔ اعاده تعيين المجموعه — مسح كامل\n"
            "➔ رتبتي / صلاحياتي / صلاحيات [معرف]\n"
            "➔ المالك / المنشئين / الادمنيه / المشرفين / المدراء\n"
            "➔ فحص المجموعه — تقرير مفصل\n"
            "➔ لقب [اللقب]"
            "</blockquote>"
        ),
        "help_locks": (
            "<b>▲ قسم الحماية</b>\n\n<blockquote>"
            "➔ حمايه المجموعه — لوحة الحماية التفاعلية\n"
            "➔ تعيين عدد التكرار [رقم]\n"
            "➔ تعيين مده اسبام [ثواني]\n"
            "➔ تعيين عدد السبام [رسائل]"
            "</blockquote>"
        ),
        "help_media": (
            "<b>■ قسم الوسائط</b>\n\n<blockquote>"
            "➔ وسائط — لوحة وسائط المجموعة\n"
            "➔ وسائط الادمن [معرف] — تقييد وسائط أدمن محدد"
            "</blockquote>"
        ),
        "help_punish": (
            "<b>▼ قسم الكتم والحظر</b>\n\n<blockquote>"
            "➔ كتم [معرف] [مدة] / فك كتم [معرف]\n"
            "➔ حظر [معرف] / فك حظر [معرف]\n"
            "➔ تحذير / مسح تحذير\n"
            "➔ تعيين عدد التحذيرات [رقم]\n"
            "➔ تعيين مده الكتم [دقائق]\n"
            "➔ تفعيل الكتم التلقائي / تعطيل الكتم التلقائي\n"
            "➔ الكتم التلقائي — لوحة الكتم التلقائي\n"
            "➔ المكتومين / المحظورين\n"
            "➔ مسح المكتومين / مسح المحظورين"
            "</blockquote>"
        ),
        "help_keywords": (
            "<b>➔ الردود التلقائية</b>\n\n<blockquote>"
            "➔ اضافة رد / تعديل رد / حذف رد [الكلمة]"
            "</blockquote>"
        ),
        "help_sub": (
            "<b>❖ الاشتراك الثانوي</b>\n\n<blockquote>"
            "➔ تعيين الاشتراك الثانوي [@قناة]\n"
            "➔ تعطيل الاشتراك الثانوي / حذف قناه\n"
            "➔ اشتراك المطور يُدار من /panel"
            "</blockquote>"
        ),
        "help_stats": (
            "<b>◈ الإحصائيات</b>\n\n<blockquote>"
            "➔ معلومات المجموعه / الاحصائيات\n"
            "➔ فحص المجموعه"
            "</blockquote>"
        ),
    }

    if data == "help_back":
        await query.edit_message_text(
            "<b>❖ لوحة الأوامر</b>\n\n<blockquote>اختر القسم المطلوب:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(_MAIN_MENU_ROWS),
        )
        return

    if data == "help_games":
        games_kb = keyboard([
            [btn("تفعيل الألعاب", "games_enable_cb", style="success"),
             btn("تعطيل الألعاب", "games_disable_cb", style="danger")],
            [btn("◀ رجوع", "help_back", style="danger")],
        ])
        await query.edit_message_text(
            "<b>❖ قسم الترفيه، الألعاب والموسيقى</b>\n\n"
            "<b>◀ أوامر الموسيقى والتحميل:</b>\n"
            "<blockquote>"
            "◈ تحميل + اسم الأغنية (تحميل مباشر عالي الجودة)\n"
            "◈ يوت + اسم الأغنية (تحميل بديل سريع)\n"
            "◈ بحث + اسم الأغنية (عرض مصفوفة أزرار خيارات متعددة)"
            "</blockquote>\n\n"
            "<b>◀ أوامر الألعاب والتسلية:</b>\n"
            "<blockquote>"
            "◈ سؤال / صح ام خطا (تحدي المعلومات والخيارات)\n"
            "◈ xo (بدء تحدي إكس أوه تفاعلي بالأزرار)\n"
            "◈ تحدي الرياضيات (سباق المعادلات الحسابية السريعة)\n"
            "◈ حجرة ورقة مقص (تحدي الاختيارات المخفية)\n"
            "◈ حقل الالغام (شبكة الحظ وجمع النقاط الجماعية)\n"
            "◈ تخمين الرقم (تخمين الرقم السري في 5 محاولات)"
            "</blockquote>\n\n"
            "<b>◀ إحصائيات الترفيه:</b>\n"
            "<blockquote>"
            "◈ احصائياتي (عرض رصيدك ونقاطك ونسب الفوز)\n"
            "◈ ترتيب اللاعبين (لوحة شرف توب 10 في المجموعة)"
            "</blockquote>\n\n"
            "<b>◀ التحكم بالإعدادات (للمدراء فقط):</b>\n"
            "<blockquote>"
            "◈ تفعيل الالعاب / تعطيل الالعاب"
            "</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=games_kb,
        )
        return

    if data in texts:
        await query.edit_message_text(texts[data], parse_mode=ParseMode.HTML, reply_markup=back)


async def cmd_developer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    profile = db.get_dev_profile()
    username = profile.get("username", "")
    source = profile.get("source_channel", "")
    if not username:
        await msg.reply_text("<b>◈ لم يتم تعيين ملف المطور بعد.</b>", parse_mode=ParseMode.HTML)
        return
    link = f"https://t.me/{username}"
    kb_rows = [[btn("➔ تواصل مع المطور", url=link, style="primary")]]
    if source:
        kb_rows.append([btn("قناة السورس", url=source, style="primary")])
    await msg.reply_text(
        f"<b>❖ ملف المطور</b>\n\n<blockquote>➔ المطور: <b>@{esc(username)}</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(kb_rows),
    )


async def route_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return

    raw = msg.text.strip()
    norm = normalize_arabic(raw)

    from modules import ranks, punishments, media_filters, locks, stats, subscriptions
    from modules.antispam import cmd_set_spam_window, cmd_set_spam_count, cmd_set_repetition
    from modules.staff_media import cmd_staff_media_panel
    from modules.whispers import cmd_whisper_group

    # ── همسه ─────────────────────────────────────────────
    if norm in ("همسه", "همسة"):
        await cmd_whisper_group(update, context)
        return

    # ── مطور ─────────────────────────────────────────────
    if norm in ("مطور", "المطور"):
        await cmd_developer_profile(update, context)
        return

    from modules.youtube import cmd_download, cmd_search_music
    from modules.games import (
        cmd_mcq_quiz, cmd_tf_quiz, cmd_xo, cmd_math_challenge,
        cmd_rps, cmd_minefield, cmd_guess,
        cmd_my_stats, cmd_leaderboard,
        cmd_enable_games, cmd_disable_games,
    )

    # ── YouTube music ─────────────────────────────────────
    for prefix in ("تحميل ", "يوت "):
        if raw.startswith(prefix):
            context.args = raw[len(prefix):].strip().split()
            await cmd_download(update, context)
            return
    if raw.startswith("بحث "):
        context.args = raw[len("بحث "):].strip().split()
        await cmd_search_music(update, context)
        return

    # ── Prefix commands ───────────────────────────────────
    prefix_routes = [
        ("تعيين عدد التحذيرات", 3, punishments.cmd_set_warn_count),
        ("تعيين مده الكتم", 3, punishments.cmd_set_mute_duration),
        ("تعيين عدد التكرار", 3, cmd_set_repetition),
        ("تعيين مده اسبام", 3, cmd_set_spam_window),
        ("تعيين عدد السبام", 3, cmd_set_spam_count),
        ("تعيين الاشتراك الثانوي", 3, subscriptions.cmd_set_secondary_sub),
        ("اشتراك اجباري", 2, subscriptions.cmd_mandatory_sub),
        ("تعديل القناه", 2, subscriptions.cmd_modify_channel),
        ("حذف رد", 2, _wrap_delete_response),
        ("لقب", 1, ranks.cmd_set_title),
    ]
    for trigger, word_count, handler in prefix_routes:
        if raw.startswith(trigger):
            parts = raw.split(None, word_count)
            context.args = parts[word_count:] if len(parts) > word_count else []
            if word_count == 1:
                context.args = raw[len(trigger):].strip().split()
            await handler(update, context)
            return

    # ── وسائط الادمن ──────────────────────────────────────
    if norm.startswith("وسائط الادمن") or norm.startswith("وسائط ادمن"):
        rest = raw.split(None, 2)
        context.args = rest[2:] if len(rest) > 2 else []
        await cmd_staff_media_panel(update, context)
        return

    # ── Exact subscription commands ───────────────────────
    if norm in ("حذف قناه", "حذف القناه"):
        await subscriptions.cmd_delete_secondary_channel(update, context)
        return
    if norm == "تعطيل الاشتراك الثانوي":
        await subscriptions.cmd_disable_secondary_sub(update, context)
        return
    if norm == "تعطيل الاشتراك الاجباري":
        await subscriptions.cmd_disable_sub(update, context)
        return

    # ── Punishment commands ───────────────────────────────
    if norm.startswith("كتم"):
        context.args = raw[len("كتم"):].strip().split()
        await punishments.cmd_mute(update, context)
        return
    if norm in ("فك كتم", "فك الكتم"):
        rest = raw.split(None, 2)
        context.args = [rest[2]] if len(rest) > 2 else []
        await punishments.cmd_unmute(update, context)
        return
    # ── مسح N ─────────────────────────────────────────────
    if norm.startswith("مسح ") and not norm.startswith("مسح المكتومين") and not norm.startswith("مسح المحظورين"):
        parts = raw.split(None, 1)
        if len(parts) > 1 and parts[1].isdigit():
            context.args = [parts[1]]
            await punishments.cmd_mass_delete(update, context)
            return

    if norm.startswith("حظر"):
        context.args = raw.split()[1:]
        await punishments.cmd_ban(update, context)
        return
    if norm in ("فك حظر", "فك الحظر"):
        rest = raw.split(None, 2)
        context.args = [rest[2]] if len(rest) > 2 else []
        await punishments.cmd_unban(update, context)
        return

    # ── Promote/demote with optional ID ──────────────────
    promote_map = {
        "رفع منشئ": ranks.cmd_promote_creator,
        "تنزيل منشئ": ranks.cmd_demote_creator,
        "رفع ادمن": ranks.cmd_promote_admin,
        "تنزيل ادمن": ranks.cmd_demote_admin,
        "رفع مشرف": ranks.cmd_promote_moderator,
        "تنزيل مشرف": ranks.cmd_demote_moderator,
    }
    for trigger, handler in promote_map.items():
        norm_t = normalize_arabic(trigger)
        if norm == norm_t or norm.startswith(norm_t + " "):
            context.args = raw[len(trigger):].strip().split()
            await handler(update, context)
            return

    # ── صلاحيات ──────────────────────────────────────────
    if norm.startswith("صلاحيات"):
        rest = raw.split(None, 1)
        context.args = rest[1].split() if len(rest) > 1 else []
        await ranks.cmd_check_permissions(update, context)
        return

    # ── Simple exact-match routes (open to ALL members) ──
    simple_routes = {
        # ── Games ──────────────────────────────────────────
        "سؤال": cmd_mcq_quiz,
        "صح ام خطا": cmd_tf_quiz,
        "xo": cmd_xo,
        "تحدي الرياضيات": cmd_math_challenge,
        "حجره ورقه مقص": cmd_rps,
        "حجرة ورقة مقص": cmd_rps,
        "حقل الالغام": cmd_minefield,
        "تخمين الرقم": cmd_guess,
        "احصائياتي": cmd_my_stats,
        "ترتيب اللاعبين": cmd_leaderboard,
        "تفعيل الالعاب": cmd_enable_games,
        "تعطيل الالعاب": cmd_disable_games,
        # ── Ranks ──────────────────────────────────────────
        "رتبتي": ranks.cmd_my_rank,
        "صلاحياتي": ranks.cmd_my_permissions,
        "المالك": ranks.cmd_owner_info,
        "المنشئين": ranks.cmd_list_creators,
        "الادمنيه": ranks.cmd_list_admins,
        "المشرفين": ranks.cmd_list_moderators,
        "المدراء": ranks.cmd_all_staff,
        "تحذير": punishments.cmd_warn,
        "مسح تحذير": punishments.cmd_unwarn,
        "المكتومين": punishments.cmd_list_muted,
        "المحظورين": punishments.cmd_list_banned,
        "مسح المكتومين": punishments.cmd_bulk_unmute,
        "مسح المحظورين": punishments.cmd_bulk_unban,
        "كتم تلقائي": punishments.cmd_auto_mute_panel,
        "الكتم التلقائي": punishments.cmd_auto_mute_panel,
        "تفعيل الكتم التلقائي": punishments.cmd_enable_auto_mute,
        "تعطيل الكتم التلقائي": punishments.cmd_disable_auto_mute,
        "وسائط": media_filters.cmd_media,
        "حمايه المجموعه": locks.cmd_group_protection,
        "معلومات المجموعه": stats.cmd_group_stats,
        "الاحصائيات": stats.cmd_group_stats,
        "فحص المجموعه": ranks.cmd_audit_group,
        "فحص المجموعة": ranks.cmd_audit_group,
        "تنزيل الكل": ranks.cmd_mass_demote,
        "اعاده تعيين المجموعه": ranks.cmd_reset_group,
        "اوامر": cmd_main_menu,
        "بوت": cmd_main_menu,
    }
    for trigger, handler in simple_routes.items():
        if norm == normalize_arabic(trigger):
            context.args = []
            await handler(update, context)
            return


async def _wrap_delete_response(update, context):
    from modules.keywords import cmd_delete_response
    await cmd_delete_response(update, context)
