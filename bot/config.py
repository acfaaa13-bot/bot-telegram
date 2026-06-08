import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MONGODB_URL = os.environ["MONGODB_URL"]
DEVELOPER_ID = int(os.environ["DEVELOPER_ID"])

DB_NAME = "telegram_bot"

RANKS = {
    "developer": "❖ المطور",
    "owner": "✦ المالك",
    "creator": "◈ المنشئ",
    "admin": "▲ الأدمن",
    "moderator": "▼ المشرف",
    "member": "○ عضو",
}

FLOOD_MAX_MESSAGES = 4
FLOOD_TIME_WINDOW = 3
