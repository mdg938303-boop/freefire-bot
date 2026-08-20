"""
Entry point. Auto-detects mode:
  - No PORT env var -> POLLING (local machine / VPS / Termux)
  - PORT env var set -> WEBHOOK (Render, or any $PORT-based host)

Also runs a background scheduler that periodically checks API-fulfilled
orders (status=PROCESSING) against the provider and auto-completes /
auto-refunds them.
"""
import asyncio
import logging
import os

from sqlalchemy import select

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
from database.database import SessionLocal, get_session, init_db
from handlers import admin, deposit, orders, referral, user, nav
from services.mraipay_client import MrAiPayClient, MrAiPayError
from services.order_sync import sync_all_processing_orders
from services.payments import get_mraipay_config, record_auto_deposit_if_new

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

ORDER_SYNC_INTERVAL_SECONDS = 60

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

dp.include_router(nav.router)
dp.include_router(admin.router)
dp.include_router(deposit.router)
dp.include_router(orders.router)
dp.include_router(referral.router)
dp.include_router(user.router)

WEBHOOK_PATH = "/webhook"
WEBHOOK_BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL")
PORT = os.getenv("PORT")


async def on_startup_common():
    await init_db()
    logger.info("Database initialized (empty — no packages/providers seeded).")


def start_order_sync_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        sync_all_processing_orders, "interval", seconds=ORDER_SYNC_INTERVAL_SECONDS,
        args=[bot, SessionLocal], id="order_status_sync", max_instances=1, coalesce=True,
    )
    scheduler.start()
    return scheduler


async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="Free Fire Top-up Bot is running.")


def _payment_result_html(title: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: sans-serif; background:#0f1115; color:#eee; display:flex; align-items:center;
       justify-content:center; height:100vh; margin:0; text-align:center; padding:20px; box-sizing:border-box; }}
.card {{ background:#1a1d24; padding:32px 24px; border-radius:16px; max-width:420px; }}
h1 {{ font-size:22px; margin-bottom:12px; }}
p {{ color:#aaa; line-height:1.5; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>"""


async def payment_success(request: web.Request) -> web.Response:
    """
    Mr Ai Pay সফল পেমেন্টের পর গ্রাহকের ব্রাউজারকে এই URL-এ redirect করে।
    ⚠️ query parameter কখনো সরাসরি বিশ্বাস করা হয় না — শুধু transaction_id
    নিয়ে সরাসরি Mr Ai Pay-এর সার্ভারের কাছে verify করা হয়, সেটাই authoritative।
    """
    transaction_id = request.query.get("transactionId")
    if not transaction_id:
        return web.Response(
            text=_payment_result_html("❌ Invalid Request", "Transaction ID পাওয়া যায়নি।"),
            content_type="text/html", status=400,
        )

    async with get_session() as session:
        config = await get_mraipay_config(session)
        if config is None:
            return web.Response(
                text=_payment_result_html("⚠️ Gateway বন্ধ আছে", "Auto Deposit এই মুহূর্তে বন্ধ আছে।"),
                content_type="text/html",
            )

        client = MrAiPayClient(config["api_key"], config["secret_key"], config["brand_key"])
        try:
            result = await client.verify_payment(transaction_id)
        except MrAiPayError:
            return web.Response(
                text=_payment_result_html("⚠️ Verify করা যায়নি", "একটু পরে Telegram বটে ফিরে গিয়ে Wallet চেক করুন।"),
                content_type="text/html",
            )

        status = result.get("status")
        amount = float(result.get("amount", 0) or 0)
        metadata = result.get("metadata") or {}
        tg_user_id = metadata.get("tg_user_id")
        payment_method = result.get("payment_method")

        from database.models import User as UserModel

        user = None
        if tg_user_id:
            user_result = await session.execute(select(UserModel).where(UserModel.id == int(tg_user_id)))
            user = user_result.scalar_one_or_none()

        if user is None:
            return web.Response(
                text=_payment_result_html("⚠️ ইউজার খুঁজে পাওয়া যায়নি", "সাপোর্টে যোগাযোগ করুন।"),
                content_type="text/html",
            )

        newly_recorded = await record_auto_deposit_if_new(
            session, user, transaction_id, amount, payment_method, str(status),
        )

    if status == "COMPLETED":
        if newly_recorded:
            try:
                from utils.helpers import fmt_money
                await bot.send_message(
                    user.id,
                    f"✅ <b>Deposit সফল হয়েছে!</b>\n\n💰 Amount: {fmt_money(amount)}\n\n"
                    "আপনার ব্যালেন্স যোগ হয়ে গেছে। Wallet চেক করুন।",
                )
            except Exception:
                pass
        return web.Response(
            text=_payment_result_html("✅ Payment Successful", "আপনার ব্যালেন্স যোগ হয়ে গেছে। এবার Telegram-এ ফিরে যান।"),
            content_type="text/html",
        )

    return web.Response(
        text=_payment_result_html("🟡 Payment Pending", f"Status: {status}. একটু পরে Telegram-এ Wallet চেক করুন।"),
        content_type="text/html",
    )


async def payment_cancel(request: web.Request) -> web.Response:
    return web.Response(
        text=_payment_result_html("❌ Payment Cancelled", "কোনো টাকা কাটা হয়নি। Telegram-এ ফিরে গিয়ে আবার চেষ্টা করতে পারেন।"),
        content_type="text/html",
    )


async def run_polling():
    logger.info("Starting in POLLING mode (local/VPS/Termux).")
    await on_startup_common()
    scheduler = start_order_sync_scheduler()
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


async def run_webhook():
    if not WEBHOOK_BASE_URL:
        raise RuntimeError(
            "PORT is set (webhook mode) but WEBHOOK_BASE_URL / RENDER_EXTERNAL_URL is missing."
        )
    logger.info("Starting in WEBHOOK mode on port %s.", PORT)
    await on_startup_common()
    scheduler = start_order_sync_scheduler()

    webhook_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info("Webhook set to %s", webhook_url)

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/payment/success", payment_success)
    app.router.add_get("/payment/cancel", payment_cancel)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=int(PORT))
    await site.start()

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)


async def main():
    if PORT:
        await run_webhook()
    else:
        await run_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

