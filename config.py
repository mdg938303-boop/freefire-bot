import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


BOT_TOKEN: str = _require("BOT_TOKEN")
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
ADMIN_IDS: set[int] = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
}
SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "@support")

CURRENCY: str = "৳"
PAGE_SIZE: int = 6
GAME_NAME: str = "Free Fire"
SERVER_LABEL: str = "Bangladesh (BD) Server"

# Render-এ auto-injected, বা অন্য webhook host-এ ম্যানুয়ালি সেট করা — এটা না
# থাকলে (local/VPS polling mode-এ) Mr Ai Pay auto-deposit ফিচার কাজ করবে না,
# কারণ payment gateway-র redirect callback পেতে একটা পাবলিক HTTPS URL লাগে।
PUBLIC_BASE_URL: str | None = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL")
