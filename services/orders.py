"""
Top-up অর্ডারের মূল লজিক।

দুই ধরনের package আছে:
  1. API-linked (Package.api_provider_id + api_service_id সেট করা) —
     অর্ডার নিশ্চিত হওয়ার সাথে সাথে provider-এর API-তে পাঠানো হয়। API সফল
     হলেই ওয়ালেট থেকে টাকা কাটা হয় (ব্যর্থ হলে কোনো চার্জ হয় না, ইউজার
     বন্ধু-বান্ধব এরর মেসেজ পায়)। Status = PROCESSING, পরে background
     scheduler (order_sync.py) provider-কে periodically জিজ্ঞেস করে
     status আপডেট করে এবং সম্পন্ন হলে ইউজারকে notify করে।

  2. Manual (provider সেট করা নেই) — আগের মতোই: টাকা সাথে সাথে কাটা হয়,
     Status = PENDING_DELIVERY, Admin ম্যানুয়ালি top-up করে "Deliver" চাপে।

দুই ক্ষেত্রেই per-user asyncio lock দিয়ে ডাবল-ট্যাপ ঠেকানো হয়।
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ApiProvider, Order, OrderStatus, Package, TransactionType, User
from services.api_client import ApiClientError, get_provider_client
from services.wallet import InsufficientBalanceError, debit

_purchase_locks: dict[int, asyncio.Lock] = {}


def _lock_for(user_id: int) -> asyncio.Lock:
    if user_id not in _purchase_locks:
        _purchase_locks[user_id] = asyncio.Lock()
    return _purchase_locks[user_id]


class ProviderDispatchError(Exception):
    """API provider-এ অর্ডার পাঠাতে ব্যর্থ — কোনো টাকা কাটা হয়নি।"""


async def place_order(session: AsyncSession, user: User, package: Package, player_id: str) -> Order:
    lock = _lock_for(user.id)
    async with lock:
        result = await session.execute(select(Package).where(Package.id == package.id))
        pkg = result.scalar_one_or_none()
        if pkg is None or not pkg.is_active:
            raise ValueError("Package is no longer available.")

        # ব্যালেন্স আগে চেক করা হয় (deduct না করেই) — insufficient balance
        # হলে অযথা provider API কল হবে না।
        result = await session.execute(select(User).where(User.id == user.id))
        fresh_user = result.scalar_one()
        if float(fresh_user.balance) < float(pkg.price):
            raise InsufficientBalanceError()

        if pkg.api_provider_id and pkg.api_service_id:
            return await _place_api_order(session, fresh_user, pkg, player_id)
        else:
            return await _place_manual_order(session, fresh_user, pkg, player_id)


async def _place_api_order(session: AsyncSession, user: User, pkg: Package, player_id: str) -> Order:
    provider_result = await session.execute(select(ApiProvider).where(ApiProvider.id == pkg.api_provider_id))
    provider = provider_result.scalar_one_or_none()
    if provider is None or not provider.is_active:
        raise ProviderDispatchError("প্রোভাইডার বর্তমানে নিষ্ক্রিয়। একটু পরে চেষ্টা করুন বা সাপোর্টে যোগাযোগ করুন।")

    client = get_provider_client(provider)
    try:
        api_order_id = await client.add_order(pkg.api_service_id, player_id, quantity=1)
    except ApiClientError as exc:
        raise ProviderDispatchError(f"প্রোভাইডার অর্ডার গ্রহণ করেনি: {exc}") from exc

    # API সফল হয়েছে — এখন টাকা কাটা ও order row তৈরি, একই atomic ব্লকে।
    await debit(session, user, float(pkg.price), TransactionType.PURCHASE, note=f"Top-up: {pkg.name}")

    order = Order(
        user_id=user.id, package_id=pkg.id, package_name_snapshot=pkg.name,
        price_paid=pkg.price, player_id=player_id, status=OrderStatus.PROCESSING,
        api_provider_id=provider.id, api_order_id=api_order_id,
    )
    session.add(order)
    user.last_player_id = player_id
    await session.flush()
    await session.commit()
    return order


async def _place_manual_order(session: AsyncSession, user: User, pkg: Package, player_id: str) -> Order:
    await debit(session, user, float(pkg.price), TransactionType.PURCHASE, note=f"Top-up: {pkg.name}")

    order = Order(
        user_id=user.id, package_id=pkg.id, package_name_snapshot=pkg.name,
        price_paid=pkg.price, player_id=player_id, status=OrderStatus.PENDING_DELIVERY,
    )
    session.add(order)
    user.last_player_id = player_id
    await session.flush()
    await session.commit()
    return order
