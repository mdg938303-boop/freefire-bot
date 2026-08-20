"""
Periodically (APScheduler থেকে কল হয়) সব PROCESSING অর্ডার (যেগুলো API-তে
পাঠানো হয়েছে) চেক করে provider-এর status endpoint-এ, এবং:

  - completed হলে -> Order.DELIVERED, ইউজারকে notify
  - cancelled/failed/refunded হলে -> টাকা refund, Order.CANCELLED, ইউজারকে notify
  - অন্য কিছু (pending/processing/in progress) -> শুধু api_status/last_api_sync আপডেট
"""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import ApiProvider, Order, OrderStatus, TransactionType, User
from services.api_client import ApiClientError, get_provider_client, STATUS_COMPLETED, STATUS_FAILED
from services.wallet import credit

logger = logging.getLogger(__name__)


async def sync_all_processing_orders(bot: Bot, session_pool: async_sessionmaker) -> None:
    async with session_pool() as session:
        result = await session.execute(
            select(Order).where(Order.status == OrderStatus.PROCESSING, Order.api_order_id.is_not(None))
        )
        orders = result.scalars().all()

        for order in orders:
            if not order.api_provider_id:
                continue
            provider_result = await session.execute(select(ApiProvider).where(ApiProvider.id == order.api_provider_id))
            provider = provider_result.scalar_one_or_none()
            if provider is None or not provider.is_active:
                continue

            client = get_provider_client(provider)
            try:
                status_result = await client.get_status(order.api_order_id)
            except ApiClientError as exc:
                logger.info("Order %s status sync failed: %s", order.order_code, exc)
                continue

            normalized_status = status_result.get("status", "processing")
            order.api_status = status_result.get("raw") or order.api_status
            order.last_api_sync = datetime.utcnow()

            if normalized_status == STATUS_COMPLETED:
                order.status = OrderStatus.DELIVERED
                order.delivered_at = order.last_api_sync
                await session.commit()
                await _notify_user(bot, order, delivered=True)

            elif normalized_status == STATUS_FAILED:
                user_result = await session.execute(select(User).where(User.id == order.user_id))
                user = user_result.scalar_one_or_none()
                if user:
                    await credit(session, user, float(order.price_paid), TransactionType.REFUND, note=f"Auto-refund: {order.order_code}")
                order.status = OrderStatus.CANCELLED
                await session.commit()
                await _notify_user(bot, order, delivered=False)

            else:
                await session.commit()


async def _notify_user(bot: Bot, order: Order, delivered: bool) -> None:
    try:
        if delivered:
            text = (
                f"🎉 <b>Top-up সম্পন্ন হয়েছে!</b>\n\n"
                f"💎 {order.package_name_snapshot}\n"
                f"🆔 Order: {order.order_code}\n\n"
                "গেমে গিয়ে চেক করে দেখুন। ধন্যবাদ! 🎮"
            )
        else:
            text = (
                f"🔴 <b>দুঃখিত, আপনার অর্ডার সম্পন্ন করা যায়নি।</b>\n\n"
                f"🆔 Order: {order.order_code}\n"
                "আপনার টাকা wallet-এ ফেরত দেওয়া হয়েছে।"
            )
        await bot.send_message(order.user_id, text)
    except Exception:  # noqa: BLE001
        pass
