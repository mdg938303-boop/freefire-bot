from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import desc, func, select

from config import ADMIN_IDS, PAGE_SIZE, SERVER_LABEL
from database.database import get_session
from database.models import (
    ActivityLog, ApiProvider, Deposit, DepositStatus, Order, OrderStatus, Package,
    PaymentMethod, Setting, TransactionType, User,
)
from keyboards.admin import (
    admin_back, admin_deposit_detail_kb, admin_deposits_kb,
    admin_mraipay_kb, admin_order_detail_kb, admin_orders_kb, admin_package_detail_kb,
    admin_packages_kb, admin_payment_methods_kb, admin_pkg_delivery_choice_kb,
    admin_pkg_provider_choice_kb, admin_pm_detail_kb, admin_provider_detail_kb,
    admin_provider_type_kb, admin_providers_kb, admin_referral_settings_kb,
    admin_user_detail_kb, admin_users_kb,
)
from services.api_client import ApiClientError, PROVIDER_TYPES, get_provider_client
from services.wallet import InsufficientBalanceError, credit, debit
from utils.helpers import fmt_money
from utils.states import (
    AdminBroadcastFlow, AdminDeliveryNoteFlow, AdminDepositRejectFlow,
    AdminMrAiPayFlow, AdminPackageFlow, AdminPaymentMethodFlow, AdminProviderFlow,
    AdminReferralSettingsFlow, AdminUserBalanceFlow,
)

router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def _log(session, actor_id: int, action: str, details: str | None = None):
    session.add(ActivityLog(actor_id=actor_id, action=action, details=details))
    await session.flush()


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not _is_admin(message.from_user.id):
        return
    from keyboards.admin import admin_reply_kb

    await message.answer(
        "🛠️ <b>Admin Panel</b>\n\nনিচের কিবোর্ড থেকে যা করতে চান বেছে নিন।",
        reply_markup=admin_reply_kb(),
    )


@router.callback_query(F.data == "adm:home")
async def cb_admin_home(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    from aiogram.types import InlineKeyboardMarkup as _IKM

    await call.message.edit_text(
        "🛠️ <b>Admin Panel</b>\n\nনিচের কিবোর্ড থেকে যা করতে চান বেছে নিন।",
        reply_markup=_IKM(inline_keyboard=[]),
    )
    await call.answer()


# ---------------- DASHBOARD ----------------

async def _render_dashboard(session):
    from datetime import datetime, time

    total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    banned_users = (await session.execute(select(func.count(User.id)).where(User.is_banned == True))).scalar() or 0  # noqa: E712
    total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    total_sales = (await session.execute(select(func.coalesce(func.sum(Order.price_paid), 0)))).scalar() or 0
    pending_deposits = (await session.execute(select(func.count(Deposit.id)).where(Deposit.status == DepositStatus.PENDING))).scalar() or 0
    pending_orders = (await session.execute(select(func.count(Order.id)).where(Order.status.in_([OrderStatus.PENDING_DELIVERY, OrderStatus.PROCESSING])))).scalar() or 0
    active_packages = (await session.execute(select(func.count(Package.id)).where(Package.is_active == True))).scalar() or 0  # noqa: E712

    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    today_orders = (await session.execute(select(func.count(Order.id)).where(Order.created_at >= today_start))).scalar() or 0
    today_revenue = (await session.execute(select(func.coalesce(func.sum(Order.price_paid), 0)).where(Order.created_at >= today_start))).scalar() or 0

    text = (
        "📊 <b>Dashboard</b>\n\n"
        f"👥 Total Users: {total_users}\n"
        f"🚫 Banned Users: {banned_users}\n\n"
        f"🛒 Total Orders: {total_orders}\n"
        f"💵 Total Sales: {fmt_money(total_sales)}\n\n"
        f"🟡 Pending Deposits: {pending_deposits}\n"
        f"🟡 Pending Orders: {pending_orders}\n\n"
        f"💎 Active Packages: {active_packages}\n\n"
        "📅 <b>Today</b>\n"
        f"Orders: {today_orders} | Revenue: {fmt_money(today_revenue)}"
    )
    return text, admin_back()


@router.callback_query(F.data == "adm:dash")
async def cb_dashboard(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        text, kb = await _render_dashboard(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# ---------------- PACKAGES ----------------

async def _render_packages(session):
    result = await session.execute(select(Package).order_by(desc(Package.created_at)))
    packages = result.scalars().all()
    return "💎 <b>Diamond Packages</b>", admin_packages_kb(packages)


@router.callback_query(F.data == "adm:pkgs")
async def cb_admin_packages(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        text, kb = await _render_packages(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:pkg_add")
async def cb_admin_pkg_add(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminPackageFlow.waiting_name)
    await call.message.edit_text(
        "➕ <b>Add Package</b>\n\nPackage-এর নাম লিখুন (যেমন: 100 Diamond):",
        reply_markup=admin_back("adm:pkgs"),
    )
    await call.answer()


@router.message(AdminPackageFlow.waiting_name)
async def admin_pkg_name(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminPackageFlow.waiting_diamond_amount)
    await message.answer("💎 Diamond পরিমাণ লিখুন (যেমন: 100, বা 'Weekly Membership'):")


@router.message(AdminPackageFlow.waiting_diamond_amount)
async def admin_pkg_diamond(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(diamond_amount=message.text.strip())
    await state.set_state(AdminPackageFlow.waiting_price)
    await message.answer("💰 Price লিখুন (শুধু সংখ্যা):")


@router.message(AdminPackageFlow.waiting_price)
async def admin_pkg_price(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ সঠিক price লিখুন।")
        return

    await state.update_data(price=price)
    await message.answer(
        "এই Package কীভাবে ডেলিভার হবে?\n\n"
        "⚡ <b>Automatic</b> — একটা API Provider-এর সাথে যুক্ত করলে অর্ডার এলেই "
        "স্বয়ংক্রিয়ভাবে top-up হয়ে যাবে।\n"
        "✍️ <b>Manual</b> — Admin নিজে top-up করে 'Deliver' চাপবে (আগের নিয়ম)।",
        reply_markup=admin_pkg_delivery_choice_kb(),
    )


@router.callback_query(F.data == "adm:pkg_mode_manual")
async def cb_admin_pkg_mode_manual(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await _finalize_package(call.message, state, provider_id=None, api_service_id=None, cost_price=None, is_callback=True)
    await call.answer()


@router.callback_query(F.data == "adm:pkg_mode_auto")
async def cb_admin_pkg_mode_auto(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        result = await session.execute(select(ApiProvider).where(ApiProvider.is_active == True))  # noqa: E712
        providers = result.scalars().all()
    if not providers:
        await call.message.edit_text(
            "⚠️ কোনো Active API Provider নেই। আগে 🔌 API Providers থেকে একটা যোগ করুন, "
            "অথবা Manual mode বেছে নিন।",
            reply_markup=admin_pkg_delivery_choice_kb(),
        )
        await call.answer()
        return
    await call.message.edit_text("🔌 কোন Provider ব্যবহার করবেন?", reply_markup=admin_pkg_provider_choice_kb(providers))
    await call.answer()


@router.callback_query(F.data.startswith("adm:pkg_provider:"))
async def cb_admin_pkg_provider_selected(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    provider_id = int(call.data.split(":")[2])
    await state.update_data(provider_id=provider_id)
    await state.set_state(AdminPackageFlow.waiting_provider_service_id)
    await call.message.edit_text(
        "🔢 এই Provider-এর ওয়েবসাইট/API থেকে পাওয়া <b>Service ID</b> লিখুন:",
    )
    await call.answer()


@router.message(AdminPackageFlow.waiting_provider_service_id)
async def admin_pkg_provider_service_id(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(api_service_id=message.text.strip())
    await state.set_state(AdminPackageFlow.waiting_cost_price)
    await message.answer("💵 Provider-এর দাম (cost price) লিখুন (ঐচ্ছিক, না থাকলে /skip):")


@router.message(Command("skip"), AdminPackageFlow.waiting_cost_price)
async def admin_pkg_cost_skip(message: Message, state: FSMContext):
    data = await state.get_data()
    await _finalize_package(message, state, provider_id=data["provider_id"], api_service_id=data["api_service_id"], cost_price=None)


@router.message(AdminPackageFlow.waiting_cost_price)
async def admin_pkg_cost(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    try:
        cost_price = float(message.text.strip())
    except ValueError:
        await message.answer("⚠️ সঠিক সংখ্যা লিখুন, অথবা /skip করুন।")
        return
    data = await state.get_data()
    await _finalize_package(message, state, provider_id=data["provider_id"], api_service_id=data["api_service_id"], cost_price=cost_price)


async def _finalize_package(message: Message, state: FSMContext, provider_id: int | None, api_service_id: str | None, cost_price: float | None, is_callback: bool = False):
    data = await state.get_data()
    async with get_session() as session:
        pkg = Package(
            name=data["name"], diamond_amount=data["diamond_amount"], price=data["price"], is_active=True,
            api_provider_id=provider_id, api_service_id=api_service_id, cost_price=cost_price,
        )
        session.add(pkg)
        await _log(session, message.from_user.id, "ADD_PACKAGE", data["name"])
        await session.commit()
    await state.clear()
    mode_text = "⚡ Automatic (API)" if provider_id else "✍️ Manual"
    text = f"✅ Package '{data['name']}' তৈরি হয়েছে। ({mode_text})"
    if is_callback:
        await message.edit_text(text, reply_markup=admin_back("adm:pkgs"))
    else:
        await message.answer(text, reply_markup=admin_back("adm:pkgs"))


@router.callback_query(F.data.startswith("adm:pkg:"))
async def cb_admin_pkg_detail(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    pkg_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Package).where(Package.id == pkg_id))
        pkg = result.scalar_one_or_none()
    if pkg is None:
        await call.answer("Not found.", show_alert=True)
        return
    text = (
        f"💎 <b>{pkg.name}</b>\n\n"
        f"পরিমাণ: {pkg.diamond_amount}\n"
        f"💰 বিক্রয় মূল্য: {fmt_money(pkg.price)}\n"
        f"Status: {'🟢 Active' if pkg.is_active else '🔴 Inactive'}\n\n"
    )
    if pkg.api_provider_id and pkg.api_service_id:
        text += f"⚡ Delivery: Automatic\n🔌 Provider ID: {pkg.api_provider_id}\n🔢 Service ID: {pkg.api_service_id}\n"
        if pkg.cost_price:
            profit = float(pkg.price) - float(pkg.cost_price)
            text += f"💵 Cost: {fmt_money(pkg.cost_price)} (লাভ: {fmt_money(profit)})\n"
    else:
        text += "✍️ Delivery: Manual (Admin নিজে top-up করে দেবে)\n"
    await call.message.edit_text(text, reply_markup=admin_package_detail_kb(pkg))
    await call.answer()


@router.callback_query(F.data.startswith("adm:pkg_toggle:"))
async def cb_admin_pkg_toggle(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    pkg_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Package).where(Package.id == pkg_id))
        pkg = result.scalar_one_or_none()
        if pkg:
            pkg.is_active = not pkg.is_active
            await _log(session, call.from_user.id, "TOGGLE_PACKAGE", f"{pkg.name} -> {pkg.is_active}")
            await session.commit()
    await cb_admin_pkg_detail(call)


@router.callback_query(F.data.startswith("adm:pkg_del:"))
async def cb_admin_pkg_del(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    pkg_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Package).where(Package.id == pkg_id))
        pkg = result.scalar_one_or_none()
        if pkg:
            await session.delete(pkg)
            await _log(session, call.from_user.id, "DELETE_PACKAGE", pkg.name)
            await session.commit()
    await cb_admin_packages(call)


# ---------------- ORDERS ----------------

async def _render_orders(session, page: int):
    result = await session.execute(
        select(Order).order_by(desc(Order.created_at)).offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)
    )
    orders = result.scalars().all()
    has_next = len(orders) > PAGE_SIZE
    orders = orders[:PAGE_SIZE]
    return "📦 <b>Orders</b>", admin_orders_kb(orders, page, has_next)


@router.callback_query(F.data.startswith("adm:orders:"))
async def cb_admin_orders(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    page = int(call.data.split(":")[2])
    async with get_session() as session:
        text, kb = await _render_orders(session, page)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:order:"))
async def cb_admin_order_detail(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    order_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            await call.answer("Not found.", show_alert=True)
            return
        user_result = await session.execute(select(User).where(User.id == order.user_id))
        user = user_result.scalar_one_or_none()

    status_map = {
        "PENDING_DELIVERY": "🟡 Pending Delivery",
        "PROCESSING": "⚡ Processing (automatic)",
        "DELIVERED": "🟢 Delivered",
        "CANCELLED": "🔴 Cancelled",
    }
    text = (
        f"📦 <b>Order {order.order_code}</b>\n\n"
        f"User: {user.first_name if user else order.user_id} (<code>{order.user_id}</code>)\n"
        f"Username: @{user.username if user and user.username else '—'}\n"
        f"💎 Package: {order.package_name_snapshot}\n"
        f"🎮 <b>Player ID: <code>{order.player_id}</code></b>\n"
        f"🌍 Server: {SERVER_LABEL}\n"
        f"💰 Price: {fmt_money(order.price_paid)}\n"
        f"📅 Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"Status: {status_map.get(order.status.value)}"
    )
    if order.api_order_id:
        text += f"\n\n🔌 Provider Order ID: <code>{order.api_order_id}</code>"
        if order.api_status:
            text += f"\nProvider Status: {order.api_status}"
        if order.last_api_sync:
            text += f"\nLast Sync: {order.last_api_sync.strftime('%Y-%m-%d %H:%M')}"
    if order.delivery_note:
        text += f"\n\n📝 Note: {order.delivery_note}"

    await call.message.edit_text(text, reply_markup=admin_order_detail_kb(order))
    await call.answer()


@router.callback_query(F.data.startswith("adm:deliver_note:"))
async def cb_admin_deliver_note(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    order_id = int(call.data.split(":")[2])
    await state.update_data(order_id=order_id)
    await state.set_state(AdminDeliveryNoteFlow.waiting_note)
    await call.message.edit_text("📝 Delivery note লিখুন:", reply_markup=admin_back(f"adm:order:{order_id}"))
    await call.answer()


@router.message(AdminDeliveryNoteFlow.waiting_note)
async def admin_deliver_note_entered(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    async with get_session() as session:
        result = await session.execute(select(Order).where(Order.id == data["order_id"]))
        order = result.scalar_one_or_none()
        if order:
            order.delivery_note = message.text.strip()
            await session.commit()
    await state.clear()
    await message.answer("✅ Note সংরক্ষণ করা হয়েছে।", reply_markup=admin_back(f"adm:order:{data['order_id']}"))


@router.callback_query(F.data.startswith("adm:deliver:"))
async def cb_admin_deliver(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    order_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None or order.status.value not in ("PENDING_DELIVERY", "PROCESSING"):
            await call.answer("এই অর্ডার আগেই process হয়েছে।", show_alert=True)
            return
        from datetime import datetime
        order.status = OrderStatus.DELIVERED
        order.delivered_at = datetime.utcnow()
        await _log(session, call.from_user.id, "DELIVER_ORDER", order.order_code)
        await session.commit()
        user_id, order_code, pkg_name, note = order.user_id, order.order_code, order.package_name_snapshot, order.delivery_note

    try:
        text = (
            f"🎉 <b>Top-up সম্পন্ন হয়েছে!</b>\n\n"
            f"💎 {pkg_name}\n"
            f"🆔 Order: {order_code}\n\n"
            "গেমে গিয়ে চেক করে দেখুন। ধন্যবাদ! 🎮"
        )
        if note:
            text += f"\n\n📝 {note}"
        await call.bot.send_message(user_id, text)
    except Exception:
        await call.answer("⚠️ User-কে message পাঠানো যায়নি (হয়তো bot block করেছে)।", show_alert=True)

    await call.message.edit_text(f"✅ Order {order_code} delivered!", reply_markup=admin_back("adm:orders:0"))
    await call.answer()


@router.callback_query(F.data.startswith("adm:order_cancel:"))
async def cb_admin_order_cancel(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    order_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None or order.status.value not in ("PENDING_DELIVERY", "PROCESSING"):
            await call.answer("Cannot cancel.", show_alert=True)
            return
        user_result = await session.execute(select(User).where(User.id == order.user_id))
        user = user_result.scalar_one()
        await credit(session, user, float(order.price_paid), TransactionType.REFUND, note=f"Refund: {order.order_code}")
        order.status = OrderStatus.CANCELLED
        await _log(session, call.from_user.id, "CANCEL_ORDER", order.order_code)
        await session.commit()
        user_id, order_code = user.id, order.order_code

    try:
        await call.bot.send_message(user_id, f"🔴 আপনার Order {order_code} বাতিল হয়েছে এবং টাকা refund করা হয়েছে।")
    except Exception:
        pass

    await call.message.edit_text("✅ Order cancelled & refunded.", reply_markup=admin_back("adm:orders:0"))
    await call.answer()


# ---------------- DEPOSITS ----------------

async def _render_deposits(session, page: int):
    result = await session.execute(
        select(Deposit).order_by(desc(Deposit.created_at)).offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)
    )
    deposits = result.scalars().all()
    has_next = len(deposits) > PAGE_SIZE
    deposits = deposits[:PAGE_SIZE]
    return "💰 <b>Deposit Requests</b>", admin_deposits_kb(deposits, page, has_next)


@router.callback_query(F.data.startswith("adm:deps:"))
async def cb_admin_deposits(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    page = int(call.data.split(":")[2])
    async with get_session() as session:
        text, kb = await _render_deposits(session, page)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:dep:"))
async def cb_admin_dep_detail(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    dep_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(Deposit).where(Deposit.id == dep_id))
        dep = result.scalar_one_or_none()
        if dep is None:
            await call.answer("Not found.", show_alert=True)
            return
        user_result = await session.execute(select(User).where(User.id == dep.user_id))
        user = user_result.scalar_one_or_none()
        method_result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == dep.method_id))
        method = method_result.scalar_one_or_none()

    status_map = {"PENDING": "🟡 Pending", "APPROVED": "🟢 Approved", "REJECTED": "🔴 Rejected"}
    text = (
        f"💰 <b>Deposit #{dep.id}</b>\n\n"
        f"User: {user.first_name if user else dep.user_id} (<code>{dep.user_id}</code>)\n"
        f"Method: {method.method_name if method else '—'}\n"
        f"Amount: {fmt_money(dep.amount)}\n"
        f"Transaction ID: {dep.transaction_id}\n"
        f"Sender Number: {dep.sender_number}\n"
        f"Request Time: {dep.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"Status: {status_map.get(dep.status.value)}"
    )
    if dep.status == DepositStatus.REJECTED and dep.rejection_reason:
        text += f"\nReason: {dep.rejection_reason}"

    await call.message.edit_text(text, reply_markup=admin_deposit_detail_kb(dep))
    await call.answer()


@router.callback_query(F.data.startswith("adm:dep_approve:"))
async def cb_admin_dep_approve(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    dep_id = int(call.data.split(":")[2])
    from services.payments import approve_deposit
    async with get_session() as session:
        result = await session.execute(select(Deposit).where(Deposit.id == dep_id))
        dep = result.scalar_one_or_none()
        if dep is None or dep.status != DepositStatus.PENDING:
            await call.answer("Cannot approve.", show_alert=True)
            return
        await approve_deposit(session, dep)
        method_result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == dep.method_id))
        method = method_result.scalar_one_or_none()
        await _log(session, call.from_user.id, "APPROVE_DEPOSIT", f"#{dep.id}")
        user_id, amount, txn_id, method_name = dep.user_id, dep.amount, dep.transaction_id, (method.method_name if method else "—")

    try:
        await call.bot.send_message(
            user_id,
            "✅ <b>Deposit Approved</b>\n\n"
            f"Amount: {fmt_money(amount)}\n"
            f"Method: {method_name}\n"
            f"Transaction ID: {txn_id}\n\n"
            "Your wallet has been credited.",
        )
    except Exception:
        pass

    await call.message.edit_text(f"✅ Deposit #{dep_id} approved.", reply_markup=admin_back("adm:deps:0"))
    await call.answer()


@router.callback_query(F.data.startswith("adm:dep_reject:"))
async def cb_admin_dep_reject(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    dep_id = int(call.data.split(":")[2])
    await state.update_data(dep_id=dep_id)
    await state.set_state(AdminDepositRejectFlow.waiting_reason)
    await call.message.edit_text("❌ Rejection reason লিখুন (বা /skip):", reply_markup=admin_back(f"adm:dep:{dep_id}"))
    await call.answer()


@router.message(Command("skip"), AdminDepositRejectFlow.waiting_reason)
async def admin_dep_reject_skip(message: Message, state: FSMContext):
    await _finalize_reject(message, state, None)


@router.message(AdminDepositRejectFlow.waiting_reason)
async def admin_dep_reject_reason(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await _finalize_reject(message, state, message.text.strip())


async def _finalize_reject(message: Message, state: FSMContext, reason: str | None):
    from services.payments import reject_deposit
    data = await state.get_data()
    async with get_session() as session:
        result = await session.execute(select(Deposit).where(Deposit.id == data["dep_id"]))
        dep = result.scalar_one_or_none()
        if dep is None or dep.status != DepositStatus.PENDING:
            await state.clear()
            await message.answer("Cannot reject.")
            return
        await reject_deposit(session, dep, reason)
        await _log(session, message.from_user.id, "REJECT_DEPOSIT", f"#{dep.id}")
        user_id = dep.user_id

    try:
        text = "❌ <b>Deposit Rejected</b>"
        if reason:
            text += f"\n\nReason: {reason}"
        await message.bot.send_message(user_id, text)
    except Exception:
        pass

    await state.clear()
    await message.answer(f"✅ Deposit #{data['dep_id']} rejected.", reply_markup=admin_back("adm:deps:0"))


# ---------------- PAYMENT METHODS ----------------

async def _render_payment_methods(session):
    result = await session.execute(select(PaymentMethod))
    methods = result.scalars().all()
    return "💳 <b>Payment Methods</b>", admin_payment_methods_kb(methods)


@router.callback_query(F.data == "adm:pms")
async def cb_admin_pms(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        text, kb = await _render_payment_methods(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:pm_add")
async def cb_admin_pm_add(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminPaymentMethodFlow.waiting_name)
    await call.message.edit_text("💳 Method Name লিখুন (যেমন: bKash):", reply_markup=admin_back("adm:pms"))
    await call.answer()


@router.message(AdminPaymentMethodFlow.waiting_name)
async def admin_pm_name(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(method_name=message.text.strip())
    await state.set_state(AdminPaymentMethodFlow.waiting_account_number)
    await message.answer("📱 Account Number লিখুন:")


@router.message(AdminPaymentMethodFlow.waiting_account_number)
async def admin_pm_number(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(account_number=message.text.strip())
    await state.set_state(AdminPaymentMethodFlow.waiting_account_type)
    await message.answer("🏷️ Account Type লিখুন (Personal/Merchant, বা /skip):")


@router.message(Command("skip"), AdminPaymentMethodFlow.waiting_account_type)
async def admin_pm_type_skip(message: Message, state: FSMContext):
    await state.update_data(account_type=None)
    await state.set_state(AdminPaymentMethodFlow.waiting_instructions)
    await message.answer("📝 Instructions লিখুন (বা /skip):")


@router.message(AdminPaymentMethodFlow.waiting_account_type)
async def admin_pm_type(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(account_type=message.text.strip())
    await state.set_state(AdminPaymentMethodFlow.waiting_instructions)
    await message.answer("📝 Instructions লিখুন (বা /skip):")


@router.message(Command("skip"), AdminPaymentMethodFlow.waiting_instructions)
async def admin_pm_instructions_skip(message: Message, state: FSMContext):
    await _finalize_pm(message, state, None)


@router.message(AdminPaymentMethodFlow.waiting_instructions)
async def admin_pm_instructions(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await _finalize_pm(message, state, message.text.strip())


async def _finalize_pm(message: Message, state: FSMContext, instructions: str | None):
    data = await state.get_data()
    async with get_session() as session:
        session.add(PaymentMethod(
            method_name=data["method_name"], account_number=data["account_number"],
            account_type=data.get("account_type"), instructions=instructions, is_active=True,
        ))
        await _log(session, message.from_user.id, "ADD_PAYMENT_METHOD", data["method_name"])
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Payment Method '{data['method_name']}' যোগ হয়েছে।", reply_markup=admin_back("adm:pms"))


@router.callback_query(F.data.startswith("adm:pm:"))
async def cb_admin_pm_detail(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    pm_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == pm_id))
        pm = result.scalar_one_or_none()
    if pm is None:
        await call.answer("Not found.", show_alert=True)
        return
    text = (
        f"💳 <b>{pm.method_name}</b>\n\n"
        f"Number: {pm.account_number}\n"
        f"Type: {pm.account_type or '—'}\n"
        f"Instructions: {pm.instructions or '—'}\n"
        f"Status: {'🟢 Active' if pm.is_active else '🔴 Inactive'}"
    )
    await call.message.edit_text(text, reply_markup=admin_pm_detail_kb(pm))
    await call.answer()


@router.callback_query(F.data.startswith("adm:pm_toggle:"))
async def cb_admin_pm_toggle(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    pm_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == pm_id))
        pm = result.scalar_one_or_none()
        if pm:
            pm.is_active = not pm.is_active
            await session.commit()
    await cb_admin_pm_detail(call)


@router.callback_query(F.data.startswith("adm:pm_del:"))
async def cb_admin_pm_del(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    pm_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == pm_id))
        pm = result.scalar_one_or_none()
        if pm:
            await session.delete(pm)
            await session.commit()
    await cb_admin_pms(call)


# ---------------- USERS ----------------

async def _render_users(session, page: int):
    result = await session.execute(
        select(User).order_by(desc(User.created_at)).offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)
    )
    users = result.scalars().all()
    has_next = len(users) > PAGE_SIZE
    users = users[:PAGE_SIZE]
    return "👥 <b>Users</b>", admin_users_kb(users, page, has_next)


@router.callback_query(F.data.startswith("adm:users:"))
async def cb_admin_users(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    page = int(call.data.split(":")[2])
    async with get_session() as session:
        text, kb = await _render_users(session, page)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_admin_user_detail(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    user_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            await call.answer("Not found.", show_alert=True)
            return
        total_orders = (await session.execute(select(func.count(Order.id)).where(Order.user_id == user_id))).scalar() or 0

    text = (
        f"👤 <b>{user.first_name}</b> (@{user.username or '—'})\n\n"
        f"🆔 User ID: <code>{user.id}</code>\n"
        f"💰 Balance: {fmt_money(user.balance)}\n"
        f"📦 Total Orders: {total_orders}\n"
        f"💵 Total Deposit: {fmt_money(user.total_deposit)}\n"
        f"🎮 শেষ Player ID: {user.last_player_id or '—'}\n"
        f"📅 Registered: {user.created_at.strftime('%Y-%m-%d')}\n"
        f"Status: {'🚫 Banned' if user.is_banned else '✅ Active'}"
    )
    await call.message.edit_text(text, reply_markup=admin_user_detail_kb(user))
    await call.answer()


@router.callback_query(F.data.startswith("adm:ban:"))
async def cb_admin_ban(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    user_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.is_banned = True
            await _log(session, call.from_user.id, "BAN_USER", str(user_id))
            await session.commit()
    await cb_admin_user_detail(call)


@router.callback_query(F.data.startswith("adm:unban:"))
async def cb_admin_unban(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    user_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.is_banned = False
            await _log(session, call.from_user.id, "UNBAN_USER", str(user_id))
            await session.commit()
    await cb_admin_user_detail(call)


@router.callback_query(F.data.startswith("adm:bal_add:"))
async def cb_admin_bal_add(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    user_id = int(call.data.split(":")[2])
    await state.update_data(user_id=user_id, action="add")
    await state.set_state(AdminUserBalanceFlow.waiting_amount)
    await call.message.edit_text("💰 কত Balance যোগ করবেন?", reply_markup=admin_back(f"adm:user:{user_id}"))
    await call.answer()


@router.callback_query(F.data.startswith("adm:bal_deduct:"))
async def cb_admin_bal_deduct(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    user_id = int(call.data.split(":")[2])
    await state.update_data(user_id=user_id, action="deduct")
    await state.set_state(AdminUserBalanceFlow.waiting_amount)
    await call.message.edit_text("💸 কত Balance কমাবেন?", reply_markup=admin_back(f"adm:user:{user_id}"))
    await call.answer()


@router.message(AdminUserBalanceFlow.waiting_amount)
async def admin_bal_amount(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ সঠিক সংখ্যা লিখুন।")
        return

    data = await state.get_data()
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == data["user_id"]))
        user = result.scalar_one_or_none()
        if user is None:
            await state.clear()
            await message.answer("User not found.")
            return
        if data["action"] == "add":
            await credit(session, user, amount, TransactionType.ADJUSTMENT, note="Admin balance addition")
            action_text = "যোগ করা হয়েছে"
        else:
            try:
                await debit(session, user, amount, TransactionType.ADJUSTMENT, note="Admin balance deduction")
            except InsufficientBalanceError:
                await message.answer("⚠️ User-এর balance যথেষ্ট নেই।")
                return
            action_text = "কমানো হয়েছে"
        await _log(session, message.from_user.id, "ADJUST_BALANCE", f"user={user.id} amount={amount}")
        await session.commit()
        user_id = user.id

    await state.clear()
    await message.answer(f"✅ {fmt_money(amount)} {action_text}।", reply_markup=admin_back(f"adm:user:{user_id}"))


# ---------------- REFERRAL SETTINGS ----------------

async def _get_setting(session, key: str, default: str) -> str:
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def _set_setting(session, key: str, value: str) -> None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.flush()


async def _render_refset(session):
    enabled = (await _get_setting(session, "referral_bonus_enabled", "true")) == "true"
    amount = await _get_setting(session, "referral_bonus_amount", "10")
    text = (
        "🎁 <b>Referral Settings</b>\n\n"
        f"Bonus Status: {'🟢 Enabled' if enabled else '🔴 Disabled'}\n"
        f"Bonus Amount: {fmt_money(amount)}\n\n"
        "একজন referred user-এর প্রথম deposit approve হলে referrer এই bonus পাবে।"
    )
    return text, admin_referral_settings_kb(enabled)


@router.callback_query(F.data == "adm:refset")
async def cb_admin_refset(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        text, kb = await _render_refset(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:refset_toggle")
async def cb_admin_refset_toggle(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        enabled = (await _get_setting(session, "referral_bonus_enabled", "true")) == "true"
        await _set_setting(session, "referral_bonus_enabled", "false" if enabled else "true")
        await _log(session, call.from_user.id, "TOGGLE_REFERRAL_BONUS", str(not enabled))
        await session.commit()
    await cb_admin_refset(call)


@router.callback_query(F.data == "adm:refset_amount")
async def cb_admin_refset_amount(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminReferralSettingsFlow.waiting_amount)
    await call.message.edit_text("💰 নতুন Bonus Amount লিখুন:", reply_markup=admin_back("adm:refset"))
    await call.answer()


@router.message(AdminReferralSettingsFlow.waiting_amount)
async def admin_refset_amount_entered(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    try:
        amount = float(message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ সঠিক সংখ্যা লিখুন।")
        return
    async with get_session() as session:
        await _set_setting(session, "referral_bonus_amount", str(amount))
        await _log(session, message.from_user.id, "SET_REFERRAL_BONUS_AMOUNT", str(amount))
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Bonus Amount {fmt_money(amount)} সেট করা হয়েছে।", reply_markup=admin_back("adm:refset"))


# ---------------- MR AI PAY (Auto bKash/Nagad/Rocket Deposit) ----------------

def _mask_key(value: str) -> str:
    if not value:
        return "❌ সেট করা নেই"
    return "•" * max(len(value) - 4, 4) + value[-4:]


async def _render_mraipay(session):
    enabled = (await _get_setting(session, "mraipay_enabled", "false")) == "true"
    api_key = await _get_setting(session, "mraipay_api_key", "")
    secret_key = await _get_setting(session, "mraipay_secret_key", "")
    brand_key = await _get_setting(session, "mraipay_brand_key", "")

    configured = bool(api_key and secret_key and brand_key)
    text = (
        "💳 <b>Auto Payment — Mr Ai Pay</b>\n\n"
        "ইউজাররা bKash/Nagad/Rocket দিয়ে সরাসরি automatic deposit করতে পারবে "
        "(Admin approve করার দরকার হবে না)।\n\n"
        f"API Key: {_mask_key(api_key)}\n"
        f"Secret Key: {_mask_key(secret_key)}\n"
        f"Brand Key: {_mask_key(brand_key)}\n\n"
        f"Status: {'🟢 Enabled' if (enabled and configured) else '🔴 Disabled'}"
    )
    if not configured:
        text += "\n\n⚠️ তিনটা key সেট না করা পর্যন্ত এটা চালু করা যাবে না।"
    return text, admin_mraipay_kb(enabled, configured)


@router.callback_query(F.data == "adm:mraipay")
async def cb_admin_mraipay(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        text, kb = await _render_mraipay(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:mraipay_key")
async def cb_admin_mraipay_key(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminMrAiPayFlow.waiting_api_key)
    await call.message.edit_text("🔑 Mr Ai Pay API-KEY লিখুন:", reply_markup=admin_back("adm:mraipay"))
    await call.answer()


@router.message(AdminMrAiPayFlow.waiting_api_key)
async def admin_mraipay_key_entered(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    async with get_session() as session:
        await _set_setting(session, "mraipay_api_key", message.text.strip())
        await _log(session, message.from_user.id, "SET_MRAIPAY_API_KEY")
        await session.commit()
    try:
        await message.delete()  # চ্যাট হিস্টোরিতে key যেন না থেকে যায়
    except Exception:
        pass
    await state.clear()
    await message.answer("✅ API Key সেভ হয়েছে।", reply_markup=admin_back("adm:mraipay"))


@router.callback_query(F.data == "adm:mraipay_secret")
async def cb_admin_mraipay_secret(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminMrAiPayFlow.waiting_secret_key)
    await call.message.edit_text("🔐 Mr Ai Pay SECRET-KEY লিখুন:", reply_markup=admin_back("adm:mraipay"))
    await call.answer()


@router.message(AdminMrAiPayFlow.waiting_secret_key)
async def admin_mraipay_secret_entered(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    async with get_session() as session:
        await _set_setting(session, "mraipay_secret_key", message.text.strip())
        await _log(session, message.from_user.id, "SET_MRAIPAY_SECRET_KEY")
        await session.commit()
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    await message.answer("✅ Secret Key সেভ হয়েছে।", reply_markup=admin_back("adm:mraipay"))


@router.callback_query(F.data == "adm:mraipay_brand")
async def cb_admin_mraipay_brand(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminMrAiPayFlow.waiting_brand_key)
    await call.message.edit_text("🏷️ Mr Ai Pay BRAND-KEY লিখুন:", reply_markup=admin_back("adm:mraipay"))
    await call.answer()


@router.message(AdminMrAiPayFlow.waiting_brand_key)
async def admin_mraipay_brand_entered(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    async with get_session() as session:
        await _set_setting(session, "mraipay_brand_key", message.text.strip())
        await _log(session, message.from_user.id, "SET_MRAIPAY_BRAND_KEY")
        await session.commit()
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    await message.answer("✅ Brand Key সেভ হয়েছে।", reply_markup=admin_back("adm:mraipay"))


@router.callback_query(F.data == "adm:mraipay_toggle")
async def cb_admin_mraipay_toggle(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        enabled = (await _get_setting(session, "mraipay_enabled", "false")) == "true"
        api_key = await _get_setting(session, "mraipay_api_key", "")
        secret_key = await _get_setting(session, "mraipay_secret_key", "")
        brand_key = await _get_setting(session, "mraipay_brand_key", "")
        if not (api_key and secret_key and brand_key):
            await call.answer("⚠️ আগে তিনটা key সেট করুন।", show_alert=True)
            return
        await _set_setting(session, "mraipay_enabled", "false" if enabled else "true")
        await _log(session, call.from_user.id, "TOGGLE_MRAIPAY", str(not enabled))
        await session.commit()
    await cb_admin_mraipay(call)


# ---------------- BROADCAST ----------------

@router.callback_query(F.data == "adm:broadcast")
async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminBroadcastFlow.waiting_message)
    await call.message.edit_text("📢 <b>Broadcast</b>\n\nসব User-কে যে message পাঠাতে চান তা লিখুন:", reply_markup=admin_back())
    await call.answer()


@router.message(AdminBroadcastFlow.waiting_message)
async def admin_broadcast_message(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        result = await session.execute(select(User.id).where(User.is_banned == False))  # noqa: E712
        user_ids = [row[0] for row in result.all()]
        await _log(session, message.from_user.id, "BROADCAST", f"to {len(user_ids)} users")
        await session.commit()

    sent, failed, blocked = 0, 0, 0
    status_msg = await message.answer(f"📢 Broadcasting to {len(user_ids)} users...")
    for uid in user_ids:
        try:
            await message.bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except Exception as e:
            if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                blocked += 1
            else:
                failed += 1

    await status_msg.edit_text(
        f"📢 <b>Broadcast Complete</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}\n🚫 Blocked: {blocked}",
        reply_markup=admin_back(),
    )


# ---------------- API PROVIDERS ----------------

def _mask(value: str) -> str:
    if not value:
        return "—"
    return "•" * max(len(value) - 4, 4) + value[-4:]


async def _render_providers(session):
    result = await session.execute(select(ApiProvider).order_by(ApiProvider.name))
    providers = result.scalars().all()
    return "🔌 <b>API Providers</b>", admin_providers_kb(providers)


@router.callback_query(F.data == "adm:providers")
async def cb_admin_providers(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    async with get_session() as session:
        text, kb = await _render_providers(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:prov_add")
async def cb_admin_prov_add(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(AdminProviderFlow.waiting_type)
    await call.message.edit_text(
        "🔌 <b>Add API Provider</b>\n\nকোন ধরনের Provider API ব্যবহার করবেন?",
        reply_markup=admin_provider_type_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm:prov_type:"))
async def cb_admin_prov_type_selected(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    provider_type = call.data.split(":")[2]
    await state.update_data(provider_type=provider_type)
    await state.set_state(AdminProviderFlow.waiting_name)
    await call.message.edit_text("🔌 প্রোভাইডারের নাম লিখুন (যেমন: Epinby):")
    await call.answer()


@router.message(AdminProviderFlow.waiting_name)
async def admin_prov_name(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(name=message.text.strip())
    data = await state.get_data()
    await state.set_state(AdminProviderFlow.waiting_base_url)
    hint = " (যেমন: https://epinby.com/api/v1)" if data.get("provider_type") == "EPINBY" else ""
    await message.answer(f"🌐 API Base URL লিখুন{hint}:")


@router.message(AdminProviderFlow.waiting_base_url)
async def admin_prov_url(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("⚠️ বৈধ URL দিন (http/https দিয়ে শুরু)।")
        return
    await state.update_data(base_url=url)
    await state.set_state(AdminProviderFlow.waiting_api_key)
    await message.answer("🔑 API Key লিখুন:")


@router.message(AdminProviderFlow.waiting_api_key)
async def admin_prov_key(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(api_key=message.text.strip())
    try:
        await message.delete()  # চ্যাট হিস্টোরিতে key যেন না থেকে যায়
    except Exception:
        pass

    data = await state.get_data()
    if data.get("provider_type") == "EPINBY":
        # Epinby-তে আলাদা secret লাগে না, সরাসরি currency-তে চলে যাই
        await state.update_data(api_secret=None)
        await state.set_state(AdminProviderFlow.waiting_currency)
        await message.answer("💱 Currency কোড লিখুন (যেমন USD, BDT):")
    else:
        await state.set_state(AdminProviderFlow.waiting_api_secret)
        await message.answer("🔐 API Secret লিখুন (না থাকলে '-' পাঠান):")


@router.message(AdminProviderFlow.waiting_api_secret)
async def admin_prov_secret(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    secret = None if message.text.strip() == "-" else message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    await state.update_data(api_secret=secret)
    await state.set_state(AdminProviderFlow.waiting_currency)
    await message.answer("💱 Currency কোড লিখুন (যেমন USD, BDT):")


@router.message(AdminProviderFlow.waiting_currency)
async def admin_prov_currency(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    async with get_session() as session:
        provider = ApiProvider(
            name=data["name"], provider_type=data.get("provider_type", "SMM_GENERIC"),
            base_url=data["base_url"], api_key=data["api_key"],
            api_secret=data.get("api_secret"), currency=message.text.strip().upper() or "USD", is_active=True,
        )
        session.add(provider)
        await _log(session, message.from_user.id, "ADD_API_PROVIDER", provider.name)
        await session.commit()
    await state.clear()
    type_label = PROVIDER_TYPES.get(provider.provider_type, provider.provider_type)
    await message.answer(
        f"✅ প্রোভাইডার যোগ হয়েছে: {provider.name} ({type_label})",
        reply_markup=admin_back("adm:providers"),
    )


@router.callback_query(F.data.startswith("adm:prov:"))
async def cb_admin_prov_detail(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    prov_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(ApiProvider).where(ApiProvider.id == prov_id))
        provider = result.scalar_one_or_none()
    if provider is None:
        await call.answer("Not found.", show_alert=True)
        return
    text = (
        f"🔌 <b>{provider.name}</b>\n\n"
        f"Type: {PROVIDER_TYPES.get(provider.provider_type, provider.provider_type)}\n"
        f"Base URL: {provider.base_url}\n"
        f"API Key: {_mask(provider.api_key)}\n"
        f"API Secret: {_mask(provider.api_secret) if provider.api_secret else '—'}\n"
        f"Currency: {provider.currency}\n"
        f"Status: {'🟢 Active' if provider.is_active else '🔴 Inactive'}"
    )
    await call.message.edit_text(text, reply_markup=admin_provider_detail_kb(provider))
    await call.answer()


@router.callback_query(F.data.startswith("adm:prov_toggle:"))
async def cb_admin_prov_toggle(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    prov_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(ApiProvider).where(ApiProvider.id == prov_id))
        provider = result.scalar_one_or_none()
        if provider:
            provider.is_active = not provider.is_active
            await _log(session, call.from_user.id, "TOGGLE_API_PROVIDER", f"{provider.name} -> {provider.is_active}")
            await session.commit()
    await cb_admin_prov_detail(call)


@router.callback_query(F.data.startswith("adm:prov_del:"))
async def cb_admin_prov_del(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    prov_id = int(call.data.split(":")[2])
    async with get_session() as session:
        linked = (await session.execute(select(func.count(Package.id)).where(Package.api_provider_id == prov_id))).scalar() or 0
        if linked:
            await call.answer("⚠️ এই প্রোভাইডারের সাথে Package যুক্ত আছে। আগে সেগুলো Manual-এ পরিবর্তন করুন বা মুছুন।", show_alert=True)
            return
        result = await session.execute(select(ApiProvider).where(ApiProvider.id == prov_id))
        provider = result.scalar_one_or_none()
        if provider:
            await session.delete(provider)
            await _log(session, call.from_user.id, "DELETE_API_PROVIDER", provider.name)
            await session.commit()
    await cb_admin_providers(call)


@router.callback_query(F.data.startswith("adm:prov_test:"))
async def cb_admin_prov_test(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    prov_id = int(call.data.split(":")[2])
    async with get_session() as session:
        result = await session.execute(select(ApiProvider).where(ApiProvider.id == prov_id))
        provider = result.scalar_one_or_none()
    if provider is None:
        await call.answer("Not found.", show_alert=True)
        return

    await call.answer("টেস্ট করা হচ্ছে...")
    client = get_provider_client(provider)
    try:
        result = await client.get_balance()
        await call.message.answer(f"✅ কানেকশন সফল।\nResponse: {result}")
    except ApiClientError as exc:
        await call.message.answer(f"❌ কানেকশন ব্যর্থ: {exc}")


# ---------------- ACTIVITY LOGS ----------------

async def _render_logs(session, page: int):
    result = await session.execute(
        select(ActivityLog).order_by(desc(ActivityLog.created_at)).offset(page * PAGE_SIZE).limit(PAGE_SIZE)
    )
    logs = result.scalars().all()

    if not logs:
        return "📝 কোনো activity log নেই।", admin_back()

    lines = ["📝 <b>Activity Logs</b>\n"]
    for log in logs:
        lines.append(f"• [{log.created_at.strftime('%m-%d %H:%M')}] {log.actor_id}: {log.action} — {log.details or ''}")

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Back", callback_data="adm:home")
    if page > 0:
        b.button(text="⬅️ Prev", callback_data=f"adm:logs:{page-1}")
    b.button(text="Next ➡️", callback_data=f"adm:logs:{page+1}")
    b.adjust(1)
    return "\n".join(lines), b.as_markup()


@router.callback_query(F.data.startswith("adm:logs:"))
async def cb_admin_logs(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer()
        return
    page = int(call.data.split(":")[2])
    async with get_session() as session:
        text, kb = await _render_logs(session, page)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()
