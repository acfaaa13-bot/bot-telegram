from pymongo import MongoClient
from config import MONGODB_URL, DB_NAME

_client = MongoClient(MONGODB_URL)
db = _client[DB_NAME]

groups_col = db["groups"]
users_col = db["users"]
custom_responses_col = db["custom_responses"]
global_replies_col = db["global_replies"]
pv_users_col = db["pv_users"]
muted_users_col = db["muted_users"]
banned_users_col = db["banned_users"]
whispers_col = db["whispers"]
bot_config_col = db["bot_config"]


def get_group(group_id: int) -> dict:
    doc = groups_col.find_one({"group_id": group_id})
    if not doc:
        doc = _default_group(group_id)
        groups_col.insert_one(doc)
    return doc


def _default_group(group_id: int) -> dict:
    return {
        "group_id": group_id,
        "join_date": None,
        "media_filters": {
            "photos": False, "videos": False, "gifs": False,
            "stickers": False, "files": False, "links": False,
            "notifications": False, "voice": False,
            "video_note": False, "contacts": False,
        },
        "locks": {
            "usernames": False, "forwarding": False, "pinning": False,
            "editing": False, "flood": False, "chat": False,
            "mandatory_sub": False, "bots": False,
        },
        "spam_config": {"window": 5, "threshold": 6},
        "repetition_limit": 3,
        "auto_mute": {"enabled": False, "max_warnings": 3, "mute_duration": 10},
        "mandatory_sub_enabled": False,
        "group_channel_id": None,
        "group_channel_link": None,
        "secondary_sub_enabled": False,
        "secondary_channel_id": None,
        "secondary_channel_link": None,
        "staff_media_locks": {},
        "bot_status": True,
    }


# ── User rank / permissions ──────────────────────────────

def get_user_rank_doc(group_id: int, user_id: int) -> dict:
    return users_col.find_one({"group_id": group_id, "user_id": user_id}) or {}


def set_user_rank(group_id: int, user_id: int, rank: str, username: str = None):
    users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"rank": rank, "username": username}},
        upsert=True,
    )


def remove_user_rank(group_id: int, user_id: int):
    users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$unset": {"rank": ""}},
    )


def get_user_permissions(group_id: int, user_id: int) -> dict:
    doc = users_col.find_one({"group_id": group_id, "user_id": user_id}) or {}
    return doc.get("permissions", {
        "change_info": False, "delete_messages": False,
        "ban_users": False, "pin_messages": False,
        "manage_calls": False, "edit_tags": False,
        "add_admins": False, "invite_link": False,
    })


def set_user_permissions(group_id: int, user_id: int, permissions: dict):
    users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"permissions": permissions}},
        upsert=True,
    )


# ── Warnings ─────────────────────────────────────────────

def add_warning(group_id: int, user_id: int) -> int:
    doc = users_col.find_one_and_update(
        {"group_id": group_id, "user_id": user_id},
        {"$inc": {"warnings": 1}},
        upsert=True, return_document=True,
    )
    return doc.get("warnings", 1)


def reset_warnings(group_id: int, user_id: int):
    users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"warnings": 0}}, upsert=True,
    )


def decrement_warning(group_id: int, user_id: int) -> int:
    doc = users_col.find_one({"group_id": group_id, "user_id": user_id}) or {}
    new_val = max(0, doc.get("warnings", 0) - 1)
    users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"warnings": new_val}}, upsert=True,
    )
    return new_val


# ── Muted / Banned ────────────────────────────────────────

def register_muted(group_id: int, user_id: int, username: str = None, timed: bool = False, until=None):
    muted_users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"username": username, "timed": timed, "until": until}},
        upsert=True,
    )


def unregister_muted(group_id: int, user_id: int):
    muted_users_col.delete_one({"group_id": group_id, "user_id": user_id})


def register_banned(group_id: int, user_id: int, username: str = None):
    banned_users_col.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"username": username}},
        upsert=True,
    )


def unregister_banned(group_id: int, user_id: int):
    banned_users_col.delete_one({"group_id": group_id, "user_id": user_id})


# ── Staff media locks ─────────────────────────────────────

def get_staff_media_locks(group_id: int, user_id: int) -> dict:
    group = get_group(group_id)
    return group.get("staff_media_locks", {}).get(str(user_id), {})


def set_staff_media_locks(group_id: int, user_id: int, locks: dict):
    groups_col.update_one(
        {"group_id": group_id},
        {"$set": {f"staff_media_locks.{user_id}": locks}},
        upsert=True,
    )


def get_all_staff_media_locks(group_id: int) -> dict:
    group = get_group(group_id)
    return group.get("staff_media_locks", {})


# ── Bot status / config ───────────────────────────────────

def get_bot_status() -> bool:
    doc = bot_config_col.find_one({"key": "status"})
    return doc.get("online", True) if doc else True


def set_bot_status(online: bool):
    bot_config_col.update_one({"key": "status"}, {"$set": {"online": online}}, upsert=True)


def get_developer_channel() -> dict:
    return bot_config_col.find_one({"key": "dev_channel"}) or {}


def set_developer_channel(channel_id, channel_link: str):
    bot_config_col.update_one(
        {"key": "dev_channel"},
        {"$set": {"channel_id": channel_id, "channel_link": channel_link}},
        upsert=True,
    )


# ── Developer subscription layer ─────────────────────────

def get_dev_sub() -> dict:
    return bot_config_col.find_one({"key": "dev_sub"}) or {
        "enabled": False, "channel_id": None, "channel_link": "", "target": "both"
    }


def set_dev_sub(channel_id, channel_link: str, target: str = "both", enabled: bool = True):
    bot_config_col.update_one(
        {"key": "dev_sub"},
        {"$set": {"enabled": enabled, "channel_id": channel_id,
                  "channel_link": channel_link, "target": target}},
        upsert=True,
    )


def set_dev_sub_state(enabled: bool):
    bot_config_col.update_one({"key": "dev_sub"}, {"$set": {"enabled": enabled}}, upsert=True)


def set_dev_sub_target(target: str):
    bot_config_col.update_one({"key": "dev_sub"}, {"$set": {"target": target}}, upsert=True)


# ── Developer profile ─────────────────────────────────────

def get_dev_profile() -> dict:
    return bot_config_col.find_one({"key": "dev_profile"}) or {}


def set_dev_username(username: str):
    bot_config_col.update_one({"key": "dev_profile"}, {"$set": {"username": username}}, upsert=True)


def set_source_channel(channel_link: str):
    bot_config_col.update_one({"key": "dev_profile"}, {"$set": {"source_channel": channel_link}}, upsert=True)


# ── Secondary developers ──────────────────────────────────

def get_secondary_devs() -> list:
    doc = bot_config_col.find_one({"key": "secondary_devs"})
    return doc.get("user_ids", []) if doc else []


def add_secondary_dev(user_id: int):
    bot_config_col.update_one(
        {"key": "secondary_devs"},
        {"$addToSet": {"user_ids": user_id}},
        upsert=True,
    )


def remove_secondary_dev(user_id: int):
    bot_config_col.update_one(
        {"key": "secondary_devs"},
        {"$pull": {"user_ids": user_id}},
    )


# ── PV locks ─────────────────────────────────────────────

def get_pv_lock_config() -> dict:
    doc = bot_config_col.find_one({"key": "pv_locks"})
    if not doc:
        return {"photos": False, "stickers": False, "files": False,
                "videos": False, "voice": False, "editing": False}
    return doc.get("locks", {})


def set_pv_lock_config(locks: dict):
    bot_config_col.update_one({"key": "pv_locks"}, {"$set": {"locks": locks}}, upsert=True)


# ── Whispers ──────────────────────────────────────────────

def save_whisper(whisper_id: str, sender_id: int, target_id: int, group_id: int, content: str):
    whispers_col.insert_one({
        "whisper_id": whisper_id,
        "sender_id": sender_id,
        "target_id": target_id,
        "group_id": group_id,
        "content": content,
    })


def get_whisper(whisper_id: str) -> dict:
    return whispers_col.find_one({"whisper_id": whisper_id}) or {}


# ── Music cache ───────────────────────────────────────────

music_cache_col = db["music_cache"]
game_players_col = db["game_players"]


def get_cached_music(video_id: str) -> dict:
    return music_cache_col.find_one({"video_id": video_id}) or {}


def set_music_cache(video_id: str, file_id: str, title: str, duration: int):
    music_cache_col.update_one(
        {"video_id": video_id},
        {"$set": {"file_id": file_id, "title": title, "duration": duration}},
        upsert=True,
    )


# ── Game players ──────────────────────────────────────────

def get_player_doc(user_id: int) -> dict:
    return game_players_col.find_one({"user_id": user_id}) or {}


def update_player_points(user_id: int, points: int, xo_wins: int = 0, xo_losses: int = 0, username: str = None):
    inc = {"points": points, "game_stats.total_games": 1 if (xo_wins or xo_losses) else 0}
    if xo_wins:
        inc["game_stats.xo_wins"] = xo_wins
    if xo_losses:
        inc["game_stats.xo_losses"] = xo_losses
    upd = {"$inc": inc}
    if username:
        upd["$set"] = {"username": username}
    game_players_col.update_one({"user_id": user_id}, upd, upsert=True)
