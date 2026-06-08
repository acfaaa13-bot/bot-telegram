"""
Entertainment & Gaming Engine.
Games: Quiz (سؤال/صح ام خطا), XO, Speed Math, RPS, Minefield, Number Guessing.
Stats: احصائياتي, ترتيب اللاعبين.
"""
import random
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils import esc, btn, keyboard, get_user_rank, is_staff
import database as db

# ── In-memory game state ──────────────────────────────────
_xo_games: dict = {}       # chat_id -> game dict
_rps_games: dict = {}      # chat_id -> game dict
_mine_games: dict = {}     # chat_id -> game dict
_guess_games: dict = {}    # (chat_id, user_id) -> game dict
_quiz_locks: set = set()   # (chat_id, msg_id) of answered quizzes

# ── Points per action ─────────────────────────────────────
PTS_QUIZ_CORRECT = 5
PTS_XO_WIN = 10
PTS_XO_DRAW = 2
PTS_MATH_CORRECT = 5
PTS_MINE_SAFE = 3
PTS_MINE_BOMB = -5
PTS_GUESS_WIN = 8


# ── Games enabled check ───────────────────────────────────

def _games_enabled(chat_id: int) -> bool:
    group = db.get_group(chat_id)
    return group.get("games_enabled", True)


async def cmd_enable_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"games_enabled": True}})
    await msg.reply_text("<b>✦ تم تفعيل الألعاب في هذه المجموعة.</b>", parse_mode=ParseMode.HTML)


async def cmd_disable_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    rank = await get_user_rank(msg.chat_id, msg.from_user.id, context)
    if rank not in ("developer", "owner", "creator"):
        return
    db.groups_col.update_one({"group_id": msg.chat_id}, {"$set": {"games_enabled": False}})
    await msg.reply_text("<b>▼ تم تعطيل الألعاب في هذه المجموعة.</b>", parse_mode=ParseMode.HTML)


# ── Question bank ─────────────────────────────────────────
_MCQ_BANK = [
    {"q": "ما عاصمة المملكة العربية السعودية؟", "opts": ["الرياض", "جدة", "مكة", "المدينة"], "ans": 0},
    {"q": "كم عدد أيام السنة الكبيسة؟", "opts": ["365", "366", "367", "364"], "ans": 1},
    {"q": "ما أكبر كوكب في المجموعة الشمسية؟", "opts": ["زحل", "الأرض", "المشتري", "أورانوس"], "ans": 2},
    {"q": "في أي قارة تقع مصر؟", "opts": ["آسيا", "أوروبا", "أفريقيا", "أمريكا"], "ans": 2},
    {"q": "كم عدد أضلاع المثلث؟", "opts": ["4", "3", "5", "6"], "ans": 1},
    {"q": "ما عاصمة فرنسا؟", "opts": ["برلين", "مدريد", "باريس", "لندن"], "ans": 2},
    {"q": "ما أسرع حيوان بري؟", "opts": ["الأسد", "النمر", "الفهد", "الحصان"], "ans": 2},
    {"q": "كم عدد أشهر السنة؟", "opts": ["10", "11", "12", "13"], "ans": 2},
    {"q": "ما أطول نهر في العالم؟", "opts": ["الأمازون", "النيل", "المسيسيبي", "الدانوب"], "ans": 1},
    {"q": "ما العنصر الكيميائي الذي رمزه O؟", "opts": ["ذهب", "أكسجين", "أوزون", "أوسميوم"], "ans": 1},
    {"q": "كم عدد لاعبي كرة القدم في الملعب لكل فريق؟", "opts": ["9", "10", "11", "12"], "ans": 2},
    {"q": "أي كوكب يُعرف بالكوكب الأحمر؟", "opts": ["الزهرة", "المريخ", "المشتري", "زحل"], "ans": 1},
    {"q": "ما أكبر محيطات العالم؟", "opts": ["الأطلسي", "الهندي", "الهادئ", "المتجمد"], "ans": 2},
    {"q": "في أي سنة بدأت الحرب العالمية الأولى؟", "opts": ["1912", "1914", "1916", "1918"], "ans": 1},
    {"q": "ما عاصمة اليابان؟", "opts": ["أوساكا", "كيوتو", "طوكيو", "هيروشيما"], "ans": 2},
]

_TF_BANK = [
    {"q": "الشمس هي أكبر جسم في المجموعة الشمسية.", "ans": True},
    {"q": "المحيط الأطلسي هو أكبر محيطات العالم.", "ans": False},
    {"q": "الذهب معدن.", "ans": True},
    {"q": "الأرض هي ثالث كوكب من الشمس.", "ans": True},
    {"q": "الحوت سمكة.", "ans": False},
    {"q": "باريس عاصمة بلجيكا.", "ans": False},
    {"q": "النمل الأبيض من فصيلة النمل.", "ans": False},
    {"q": "الأخطبوط له ثمانية أذرع.", "ans": True},
    {"q": "النيل هو أطول نهر في العالم.", "ans": True},
    {"q": "الإنسان يملك 206 عظمة.", "ans": True},
]


# ── MODULE 1: Quiz ────────────────────────────────────────

async def cmd_mcq_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not _games_enabled(msg.chat_id):
        return
    q = random.choice(_MCQ_BANK)
    rows = []
    for i, opt in enumerate(q["opts"]):
        rows.append([btn(opt, f"quiz_mcq_{i}_{q['ans']}_{id(q)}", style="primary")])
    await msg.reply_text(
        f"<b>❖ سؤال:</b>\n\n<blockquote>{esc(q['q'])}</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(rows),
    )


async def cmd_tf_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not _games_enabled(msg.chat_id):
        return
    q = random.choice(_TF_BANK)
    ans_i = 0 if q["ans"] else 1
    await msg.reply_text(
        f"<b>❖ صح أم خطأ؟</b>\n\n<blockquote>{esc(q['q'])}</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard([
            [btn("صح", f"quiz_tf_0_{ans_i}", style="primary"),
             btn("خطأ", f"quiz_tf_1_{ans_i}", style="primary")],
        ]),
    )


async def callback_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    msg_key = (query.message.chat_id, query.message.message_id)
    if msg_key in _quiz_locks:
        await query.answer("❖ تمت الإجابة بالفعل.", show_alert=True)
        return

    parts = query.data.split("_")
    # quiz_mcq_{chosen}_{correct}_{id}  OR  quiz_tf_{chosen}_{correct}
    quiz_type = parts[1]
    chosen = int(parts[2])
    correct = int(parts[3])

    is_correct = chosen == correct
    _quiz_locks.add(msg_key)

    user = query.from_user
    name = f"@{user.username}" if user.username else esc(user.full_name)

    if is_correct:
        db.update_player_points(user.id, PTS_QUIZ_CORRECT, xo_wins=0)
        result_text = (
            f"<b>✦ إجابة صحيحة!</b>\n\n"
            f"<blockquote>➔ {name} حصل على <b>{PTS_QUIZ_CORRECT}</b> نقطة.</blockquote>"
        )
    else:
        result_text = f"<b>▼ إجابة خاطئة.</b>\n\n<blockquote>➔ {name}</blockquote>"

    if quiz_type == "mcq":
        q_data = context.bot_data.get(f"q_{parts[4]}")
        rows = []
        q_obj = None
        for q in _MCQ_BANK:
            if str(id(q)) == parts[4]:
                q_obj = q
                break
        if q_obj:
            for i, opt in enumerate(q_obj["opts"]):
                if i == correct:
                    s = "success"
                elif i == chosen and not is_correct:
                    s = "danger"
                else:
                    s = "primary"
                rows.append([btn(opt, f"quiz_done", style=s)])
        await query.answer("✦ صحيح!" if is_correct else "▼ خطأ!")
        try:
            text = query.message.text.split("\n\n")[1] if "\n\n" in (query.message.text or "") else ""
            await query.edit_message_text(
                f"{query.message.text}\n\n{result_text}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard(rows) if rows else None,
            )
        except Exception:
            pass
    else:
        rows = []
        for i, label in enumerate(["صح", "خطأ"]):
            if i == correct:
                s = "success"
            elif i == chosen and not is_correct:
                s = "danger"
            else:
                s = "primary"
            rows.append(btn(label, "quiz_done", style=s))
        await query.answer("✦ صحيح!" if is_correct else "▼ خطأ!")
        try:
            await query.edit_message_text(
                f"{query.message.text}\n\n{result_text}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard([rows]),
            )
        except Exception:
            pass


async def callback_quiz_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("❖ انتهى السؤال.", show_alert=False)


# ── MODULE 2: XO Game ─────────────────────────────────────

def _xo_board_kb(game: dict) -> object:
    board = game["board"]
    symbols = game["symbols"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            pos = r * 3 + c
            val = board[pos]
            if val:
                pid = [p for p, s in symbols.items() if s == val]
                style = "success" if (pid and pid[0] == game["players"][0]) else "danger"
                row.append(btn(val, f"xo_move_{game['id']}_{pos}", style=style))
            else:
                row.append(btn("◈", f"xo_move_{game['id']}_{pos}", style="primary"))
        rows.append(row)
    return keyboard(rows)


def _check_winner(board: list) -> str | None:
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a, b, c in wins:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


async def cmd_xo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    if not _games_enabled(chat_id):
        return
    host = msg.from_user

    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        if target.id == host.id or target.is_bot:
            await msg.reply_text("<b>◈ لا يمكنك تحدي نفسك أو بوت.</b>", parse_mode=ParseMode.HTML)
            return
        game_id = f"{chat_id}_{host.id}"
        game = {
            "id": game_id, "board": [""] * 9,
            "players": [host.id, target.id],
            "symbols": {host.id: "X", target.id: "O"},
            "turn": host.id, "active": True,
        }
        _xo_games[chat_id] = game
        host_name = f"@{host.username}" if host.username else esc(host.full_name)
        target_name = f"@{target.username}" if target.username else esc(target.full_name)
        sent = await msg.reply_text(
            f"<b>❖ مباراة XO</b>\n\n"
            f"<blockquote>"
            f"➔ <b>{host_name}</b> (X) ضد <b>{target_name}</b> (O)\n"
            f"➔ دور: <b>{host_name}</b>"
            f"</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=_xo_board_kb(game),
        )
        game["msg_id"] = sent.message_id
    else:
        game_id = f"{chat_id}_{host.id}"
        game = {
            "id": game_id, "board": [""] * 9,
            "players": [host.id, None],
            "symbols": {host.id: "X"},
            "turn": host.id, "active": False,
        }
        _xo_games[chat_id] = game
        host_name = f"@{host.username}" if host.username else esc(host.full_name)
        sent = await msg.reply_text(
            f"<b>❖ بانتظار منافس للانضمام إلى مباراة XO...</b>\n"
            f"<blockquote>➔ المضيف: <b>{host_name}</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("قبول المباراة", f"xo_join_{host.id}", style="success")]]),
        )
        game["msg_id"] = sent.message_id


async def callback_xo_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    host_id = int(query.data.split("_")[2])
    joiner = query.from_user

    game = _xo_games.get(chat_id)
    if not game or game["players"][0] != host_id:
        await query.answer("❖ اللعبة انتهت.", show_alert=True)
        return
    if joiner.id == host_id:
        await query.answer("❖ لا يمكنك الانضمام لمباراتك.", show_alert=True)
        return
    if game["active"]:
        await query.answer("❖ اللعبة ممتلئة.", show_alert=True)
        return

    game["players"][1] = joiner.id
    game["symbols"][joiner.id] = "O"
    game["active"] = True
    await query.answer("✦ انضممت للمباراة!")

    host = game["players"][0]
    host_name = str(host)
    joiner_name = f"@{joiner.username}" if joiner.username else esc(joiner.full_name)
    try:
        cm = await context.bot.get_chat_member(chat_id, host)
        u = cm.user
        host_name = f"@{u.username}" if u.username else esc(u.full_name)
    except Exception:
        pass

    await query.edit_message_text(
        f"<b>❖ مباراة XO</b>\n\n"
        f"<blockquote>"
        f"➔ <b>{host_name}</b> (X) ضد <b>{joiner_name}</b> (O)\n"
        f"➔ دور: <b>{host_name}</b>"
        f"</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=_xo_board_kb(game),
    )


async def callback_xo_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    parts = query.data.split("_")
    pos = int(parts[3])

    game = _xo_games.get(chat_id)
    if not game or not game.get("active"):
        await query.answer("❖ لا توجد لعبة نشطة.", show_alert=True)
        return
    if query.from_user.id != game["turn"]:
        await query.answer("❖ ليس دورك.", show_alert=True)
        return
    if game["board"][pos]:
        await query.answer("❖ هذه الخانة مشغولة.", show_alert=True)
        return

    sym = game["symbols"][query.from_user.id]
    game["board"][pos] = sym
    await query.answer()

    winner_sym = _check_winner(game["board"])
    all_filled = all(game["board"])

    p1, p2 = game["players"]
    p1_name = str(p1)
    p2_name = str(p2) if p2 else "—"
    try:
        cm1 = await context.bot.get_chat_member(chat_id, p1)
        p1_name = f"@{cm1.user.username}" if cm1.user.username else esc(cm1.user.full_name)
    except Exception:
        pass
    if p2:
        try:
            cm2 = await context.bot.get_chat_member(chat_id, p2)
            p2_name = f"@{cm2.user.username}" if cm2.user.username else esc(cm2.user.full_name)
        except Exception:
            pass

    if winner_sym:
        winner_id = [pid for pid, s in game["symbols"].items() if s == winner_sym][0]
        loser_id = p1 if winner_id == p2 else p2
        winner_name = p1_name if winner_id == p1 else p2_name
        game["active"] = False
        db.update_player_points(winner_id, PTS_XO_WIN, xo_wins=1)
        if loser_id:
            db.update_player_points(loser_id, 0, xo_losses=1)
        await query.edit_message_text(
            f"<b>❖ انتهت المباراة!</b>\n\n"
            f"<blockquote>"
            f"➔ الفائز: <b>{winner_name}</b> ({winner_sym})\n"
            f"➔ جائزة: <b>{PTS_XO_WIN}</b> نقطة"
            f"</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=_xo_board_kb(game),
        )
        _xo_games.pop(chat_id, None)
    elif all_filled:
        game["active"] = False
        if p1:
            db.update_player_points(p1, PTS_XO_DRAW)
        if p2:
            db.update_player_points(p2, PTS_XO_DRAW)
        await query.edit_message_text(
            f"<b>❖ تعادل!</b>\n\n<blockquote>➔ <b>{PTS_XO_DRAW}</b> نقطة لكل لاعب.</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=_xo_board_kb(game),
        )
        _xo_games.pop(chat_id, None)
    else:
        game["turn"] = p2 if game["turn"] == p1 else p1
        turn_name = p2_name if game["turn"] == p2 else p1_name
        await query.edit_message_text(
            f"<b>❖ مباراة XO</b>\n\n"
            f"<blockquote>"
            f"➔ <b>{p1_name}</b> (X) ضد <b>{p2_name}</b> (O)\n"
            f"➔ دور: <b>{turn_name}</b>"
            f"</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=_xo_board_kb(game),
        )


# ── MODULE 3a: Speed Math ─────────────────────────────────

_math_locks: set = set()

async def cmd_math_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not _games_enabled(msg.chat_id):
        return
    a, b = random.randint(1, 30), random.randint(1, 30)
    op = random.choice(["+", "-", "×"])
    if op == "+":
        answer = a + b
    elif op == "-":
        answer = a - b
    else:
        answer = a * b

    choices = {answer}
    while len(choices) < 4:
        choices.add(random.randint(min(answer - 10, 1), max(answer + 10, 10)))
    choices = list(choices)
    random.shuffle(choices)
    correct_idx = choices.index(answer)

    q_id = f"{msg.chat_id}_{msg.message_id}"
    rows = []
    for i, ch in enumerate(choices):
        rows.append([btn(str(ch), f"math_{q_id}_{i}_{correct_idx}", style="primary")])
    await msg.reply_text(
        f"<b>❖ تحدي الرياضيات</b>\n\n"
        f"<blockquote>➔ كم يساوي: <b>{a} {op} {b}</b> ؟</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(rows),
    )


async def callback_math(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = (query.message.chat_id, query.message.message_id)
    if key in _math_locks:
        await query.answer("❖ تمت الإجابة.", show_alert=True)
        return
    parts = query.data.split("_")
    chosen, correct = int(parts[-2]), int(parts[-1])
    is_correct = chosen == correct
    _math_locks.add(key)
    user = query.from_user
    name = f"@{user.username}" if user.username else esc(user.full_name)
    if is_correct:
        db.update_player_points(user.id, PTS_MATH_CORRECT)
        await query.answer("✦ صحيح!")
        result = f"<b>✦ {name} أجاب بشكل صحيح — {PTS_MATH_CORRECT} نقطة!</b>"
    else:
        await query.answer("▼ خطأ!")
        result = f"<b>▼ {name} أجاب بشكل خاطئ.</b>"
    try:
        await query.edit_message_text(
            f"{query.message.text}\n\n{result}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


# ── MODULE 3b: Rock Paper Scissors ───────────────────────

_RPS_CHOICES = {"حجر": "✦ حجر", "ورقه": "✦ ورقة", "مقص": "✦ مقص"}
_RPS_WINS = {"حجر": "مقص", "ورقه": "حجر", "مقص": "ورقه"}


async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    if not _games_enabled(chat_id):
        return
    host = msg.from_user

    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        if target.id == host.id or target.is_bot:
            await msg.reply_text("<b>◈ لا يمكنك تحدي نفسك أو بوت.</b>", parse_mode=ParseMode.HTML)
            return
        game_id = f"{chat_id}_{host.id}"
        _rps_games[game_id] = {
            "players": [host.id, target.id],
            "choices": {}, "active": True,
        }
        host_name = f"@{host.username}" if host.username else esc(host.full_name)
        target_name = f"@{target.username}" if target.username else esc(target.full_name)
        rows = [
            [btn(c, f"rps_{game_id}_{c}", style="primary") for c in _RPS_CHOICES],
        ]
        await msg.reply_text(
            f"<b>❖ حجرة ورقة مقص</b>\n\n"
            f"<blockquote>➔ {host_name} ضد {target_name}\n➔ اختر:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(rows),
        )
    else:
        game_id = f"{chat_id}_{host.id}"
        _rps_games[game_id] = {
            "players": [host.id, None], "choices": {}, "active": False,
        }
        host_name = f"@{host.username}" if host.username else esc(host.full_name)
        await msg.reply_text(
            f"<b>❖ حجرة ورقة مقص — بانتظار منافس...</b>\n"
            f"<blockquote>➔ المضيف: {host_name}</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard([[btn("قبول التحدي", f"rps_join_{host.id}", style="success")]]),
        )


async def callback_rps_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    host_id = int(query.data.split("_")[2])
    joiner = query.from_user
    game_id = f"{chat_id}_{host_id}"
    game = _rps_games.get(game_id)
    if not game or game["active"]:
        await query.answer("❖ اللعبة غير متاحة.", show_alert=True)
        return
    if joiner.id == host_id:
        await query.answer("❖ لا يمكنك الانضمام لمباراتك.", show_alert=True)
        return
    game["players"][1] = joiner.id
    game["active"] = True
    await query.answer("✦ انضممت!")
    rows = [[btn(c, f"rps_{game_id}_{c}", style="primary") for c in _RPS_CHOICES]]
    await query.edit_message_text(
        "<b>❖ اختر:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard(rows),
    )


async def callback_rps_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_", 4)
    # rps_{game_id}_{choice}  => parts: ["rps", chat_id, host_id, choice]
    # game_id is "{chat_id}_{host_id}"
    choice = parts[-1]
    game_id = "_".join(parts[1:3])
    game = _rps_games.get(game_id)
    if not game or not game["active"]:
        await query.answer("❖ لا توجد لعبة.", show_alert=True)
        return
    user = query.from_user
    if user.id not in game["players"]:
        await query.answer("❖ أنت لست في هذه اللعبة.", show_alert=True)
        return
    if user.id in game["choices"]:
        await query.answer("❖ اخترت بالفعل.", show_alert=True)
        return
    game["choices"][user.id] = choice
    await query.answer(f"✦ اخترت: {_RPS_CHOICES[choice]}")

    if len(game["choices"]) == 2:
        p1, p2 = game["players"]
        c1, c2 = game["choices"][p1], game["choices"][p2]
        _rps_games.pop(game_id, None)

        def _name(pid):
            return str(pid)

        result = ""
        if c1 == c2:
            result = "تعادل!"
        elif _RPS_WINS[c1] == c2:
            db.update_player_points(p1, 5)
            result = f"فاز اللاعب الأول ({_RPS_CHOICES[c1]})"
        else:
            db.update_player_points(p2, 5)
            result = f"فاز اللاعب الثاني ({_RPS_CHOICES[c2]})"

        try:
            await query.edit_message_text(
                f"<b>❖ النتيجة</b>\n\n"
                f"<blockquote>"
                f"➔ اللاعب الأول: <b>{_RPS_CHOICES[c1]}</b>\n"
                f"➔ اللاعب الثاني: <b>{_RPS_CHOICES[c2]}</b>\n"
                f"➔ <b>{result}</b>"
                f"</blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ── MODULE 3c: Minefield ──────────────────────────────────

async def cmd_minefield(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    if not _games_enabled(chat_id):
        return

    # 4x4 grid, 1 bomb hidden
    bomb_pos = random.randint(0, 15)
    safe_pts = [random.randint(2, 8) for _ in range(15)]
    grid = []
    safe_i = 0
    for i in range(16):
        if i == bomb_pos:
            grid.append({"type": "bomb", "pts": 0, "revealed": False})
        else:
            grid.append({"type": "safe", "pts": safe_pts[safe_i], "revealed": False})
            safe_i += 1

    game_id = f"{chat_id}_{msg.message_id}"
    _mine_games[game_id] = {
        "grid": grid, "scores": {}, "active": True,
        "host": msg.from_user.id,
    }

    await msg.reply_text(
        "<b>❖ حقل الألغام</b>\n\n"
        "<blockquote>➔ اضغط على أي خانة. حذار من اللغم!</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=_mine_kb(game_id, grid),
    )


def _mine_kb(game_id: str, grid: list) -> object:
    rows = []
    for r in range(4):
        row = []
        for c in range(4):
            pos = r * 4 + c
            cell = grid[pos]
            if cell["revealed"]:
                if cell["type"] == "bomb":
                    row.append(btn("▼", f"mine_done", style="danger"))
                else:
                    row.append(btn(f"+{cell['pts']}", f"mine_done", style="success"))
            else:
                row.append(btn("◈", f"mine_{game_id}_{pos}", style="primary"))
        rows.append(row)
    return keyboard(rows)


async def callback_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "mine_done":
        await query.answer("❖ هذه الخانة مكشوفة.", show_alert=False)
        return
    parts = query.data.split("_", 3)
    # mine_{chat_id}_{msg_id}_{pos}
    game_id = f"{parts[1]}_{parts[2]}"
    pos = int(parts[3])
    game = _mine_games.get(game_id)
    if not game or not game["active"]:
        await query.answer("❖ اللعبة انتهت.", show_alert=True)
        return

    user = query.from_user
    cell = game["grid"][pos]
    cell["revealed"] = True

    if cell["type"] == "bomb":
        game["active"] = False
        _mine_games.pop(game_id, None)
        db.update_player_points(user.id, PTS_MINE_BOMB)
        name = f"@{user.username}" if user.username else esc(user.full_name)
        await query.answer("▼ لغم!", show_alert=True)
        try:
            await query.edit_message_text(
                f"<b>▼ انفجر اللغم!</b>\n\n"
                f"<blockquote>➔ {name} وجد اللغم — خصم {abs(PTS_MINE_BOMB)} نقطة.</blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        pts = cell["pts"]
        game["scores"][user.id] = game["scores"].get(user.id, 0) + pts
        db.update_player_points(user.id, pts)
        await query.answer(f"✦ +{pts} نقطة!")
        try:
            await query.edit_message_reply_markup(reply_markup=_mine_kb(game_id, game["grid"]))
        except Exception:
            pass


# ── MODULE 3d: Number Guessing ────────────────────────────

async def cmd_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not _games_enabled(msg.chat_id):
        return
    key = (msg.chat_id, msg.from_user.id)
    secret = random.randint(1, 50)
    _guess_games[key] = {"secret": secret, "attempts": 5, "current": 25}
    game_id = f"{msg.chat_id}_{msg.from_user.id}"
    await msg.reply_text(
        "<b>❖ تخمين الرقم</b>\n\n"
        "<blockquote>➔ خمّن رقماً بين 1 و50. لديك 5 محاولات.</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=_guess_kb(game_id, 25),
    )


def _guess_kb(game_id: str, current: int) -> object:
    return keyboard([
        [btn(f"-5 ▼", f"guess_minus5_{game_id}", style="danger"),
         btn(f"-1 ◀", f"guess_minus1_{game_id}", style="danger"),
         btn(f"[ {current} ]", f"guess_show", style="primary"),
         btn(f"+1 ▶", f"guess_plus1_{game_id}", style="success"),
         btn(f"+5 ▲", f"guess_plus5_{game_id}", style="success")],
        [btn("تأكيد التخمين", f"guess_confirm_{game_id}", style="primary")],
    ])


async def callback_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "guess_show":
        await query.answer()
        return
    parts = query.data.split("_", 2)
    action = parts[1]
    game_id_raw = parts[2]
    gparts = game_id_raw.split("_")
    chat_id, user_id = int(gparts[0]), int(gparts[1])
    key = (chat_id, user_id)

    if query.from_user.id != user_id:
        await query.answer("❖ هذه ليست لعبتك.", show_alert=True)
        return

    game = _guess_games.get(key)
    if not game:
        await query.answer("❖ اللعبة منتهية أو غير موجودة.", show_alert=True)
        return

    if action in ("plus1", "plus5", "minus1", "minus5"):
        delta = {"plus1": 1, "plus5": 5, "minus1": -1, "minus5": -5}[action]
        game["current"] = max(1, min(50, game["current"] + delta))
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=_guess_kb(game_id_raw, game["current"]))
        except Exception:
            pass
        return

    if action == "confirm":
        guess = game["current"]
        secret = game["secret"]
        game["attempts"] -= 1
        await query.answer()
        if guess == secret:
            _guess_games.pop(key, None)
            db.update_player_points(user_id, PTS_GUESS_WIN)
            try:
                await query.edit_message_text(
                    f"<b>✦ إجابة صحيحة!</b>\n\n"
                    f"<blockquote>➔ الرقم كان <b>{secret}</b>. حصلت على {PTS_GUESS_WIN} نقطة.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        hint = "أعلى ▲" if secret > guess else "أقل ▼"
        if game["attempts"] <= 0:
            _guess_games.pop(key, None)
            try:
                await query.edit_message_text(
                    f"<b>▼ انتهت المحاولات.</b>\n\n"
                    f"<blockquote>➔ الرقم الصحيح كان <b>{secret}</b>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        try:
            await query.edit_message_text(
                f"<b>❖ تخمين الرقم</b>\n\n"
                f"<blockquote>"
                f"➔ <b>{guess}</b> — {hint}\n"
                f"➔ محاولات متبقية: <b>{game['attempts']}</b>"
                f"</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=_guess_kb(game_id_raw, game["current"]),
            )
        except Exception:
            pass


# ── Stats ─────────────────────────────────────────────────

async def cmd_my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = db.get_player_doc(msg.from_user.id)
    stats = doc.get("game_stats", {})
    name = f"@{msg.from_user.username}" if msg.from_user.username else esc(msg.from_user.full_name)
    await msg.reply_text(
        f"<b>❖ إحصائيات: {name}</b>\n\n"
        f"<blockquote>"
        f"➔ النقاط الإجمالية: <b>{doc.get('points', 0)}</b>\n"
        f"➔ انتصارات XO: <b>{stats.get('xo_wins', 0)}</b>\n"
        f"➔ خسائر XO: <b>{stats.get('xo_losses', 0)}</b>\n"
        f"➔ إجمالي المباريات: <b>{stats.get('total_games', 0)}</b>"
        f"</blockquote>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    top = list(db.game_players_col.find({}).sort("points", -1).limit(10))
    if not top:
        await msg.reply_text("<b>◈ لا يوجد لاعبون بعد.</b>", parse_mode=ParseMode.HTML)
        return
    lines = []
    medals = ["❖ 1", "✦ 2", "◈ 3"]
    for i, doc in enumerate(top):
        prefix = medals[i] if i < 3 else f"▲ {i+1}"
        uid = doc.get("user_id", "?")
        username = doc.get("username", "")
        name = f"@{username}" if username else f"ID:{uid}"
        pts = doc.get("points", 0)
        lines.append(f"{prefix}. <b>{esc(name)}</b> — <b>{pts}</b> نقطة")
    await msg.reply_text(
        "<b>❖ ترتيب اللاعبين</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML,
    )
