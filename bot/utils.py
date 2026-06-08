import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
from config import DEVELOPER_ID, RANKS
import database as db


def normalize_arabic(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[أإآ]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة\b", "ه", text)
    al_commands = [
        "كتم", "وسائط", "احصائيات", "مدراء", "مكتومين",
        "محظورين", "مشرفين", "ادمنيه", "منشئين",
        "اوامر", "حمايه",
    ]
    for cmd in al_commands:
        text = re.sub(r"^ال" + cmd, cmd, text)
    return text


def esc(text: str) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def btn(text: str, callback: str = None, url: str = None, style: str = "primary") -> InlineKeyboardButton:
    kwargs = {"text": text}
    if url:
        kwargs["url"] = url
    elif callback:
        kwargs["callback_data"] = callback
    kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def keyboard(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(rows)


async def get_user_rank(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    if user_id == DEVELOPER_ID:
        return "developer"
    # Secondary developers get developer-equivalent rank
    if user_id in db.get_secondary_devs():
        return "developer"
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status == ChatMember.OWNER:
            return "owner"
    except Exception:
        pass
    doc = db.get_user_rank_doc(chat_id, user_id)
    rank = doc.get("rank")
    if rank in ("creator", "admin", "moderator"):
        return rank
    return "member"


RANK_ORDER = ["developer", "owner", "creator", "admin", "moderator", "member"]


def rank_level(rank: str) -> int:
    try:
        return RANK_ORDER.index(rank)
    except ValueError:
        return len(RANK_ORDER)


def is_higher_rank(actor_rank: str, target_rank: str) -> bool:
    return rank_level(actor_rank) < rank_level(target_rank)


async def is_staff(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    rank = await get_user_rank(chat_id, user_id, context)
    return rank in ("developer", "owner", "creator", "admin", "moderator")


def rank_badge(rank: str) -> str:
    return RANKS.get(rank, "○ عضو")


def toggle_style(enabled: bool) -> str:
    return "success" if enabled else "danger"


def toggle_label(name: str, enabled: bool) -> str:
    state = "فتح" if enabled else "قفل"
    return f"{name} ◈ {state}"
