from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy import desc, select

from config import ADMIN_IDS, PAGE_SIZE, SERVER_LABEL
from database.database import get_session
from database.models import Order, Package
from keyboards.user import back_home, orders_list_kb
from services.orders import ProviderDispatchError, place_order
from services.wallet import InsufficientBalanceError, get_or_create_user
from utils.helpers import fmt_money
from utils.states import OrderFlow

router = Router(name="orders")

_NO_INLINE = InlineKeyboardMarkup(inline_keyboard=[])


@router.callback_query(F.data.startswith("order_place:"))
async def cb_order_place(call: CallbackQuery, state: FSMContext):
    pkg_id = int(call.data.split(":")[1])
    data = await state.get_data()
    player_id = data.get("player_id")

    if not player_id:
        await call.answer("Player ID পাওয়া যায়নি, আবার চেষ্টা করুন।", show_alert=True)
        await state.clear()
        return

    async with get_session() as session:
        user = await get_or_create_user(session, call.from_user)
        await session.commit()

        if user.is_banned:
            await call.answer("🚫 আপনার অ্যাকাউন্ট ব্যান করা হয়েছে।", show_alert=True)
            return

        result = await session.execute(select(Package).where(Package.id == pkg_id))
        pkg = result.scalar_one_or_none()
        if pkg is None or not pkg.is_active:
            await call.answer("❌ এই package টি আর available নেই।", show_alert=True)
            return

        try:
            order = await place_order(session, user, pkg, player_id)
        except InsufficientBalanceError:
            await call.message.edit_text(
                f"❌ <b>Insufficient Balance</b>\n\nআপনার ব্যালেন্স {fmt_money(user.balance)}, "
                f"কিন্তু প্যাকেজের মূল্য {fmt_money(pkg.price)}।\n\n"
                "নিচের ➕ Deposit বাটনে চেপে ব্যালেন্স যোগ করুন।",
                reply_markup=_NO_INLINE,
            )
            await call.answer()
            return
        except ProviderDispatchError as exc:
            await call.message.edit_text(
                f"❌ <b>এই মুহূর্তে top-up করা যাচ্ছে না।</b>\n\n{exc}\n\n"
                "⚠️ কোনো টাকা কাটা হয়নি। একটু পরে আবার চেষ্টা করুন।",
                reply_markup=_NO_INLINE,
            )
            await call.answer()
            return

    await state.clear()
    is_auto = order.status.value == "PROCESSING"
    if is_auto:
        text = (
            "✅ <b>আপনার অর্ডার গ্রহণ করা হয়েছে!</b>\n\n"
            f"🆔 Order ID: <code>{order.order_code}</code>\n"
            f"🎮 Player ID: <code>{order.player_id}</code>\n"
            f"⚡ Status: Processing (automatic)\n\n"
            "আপনার top-up প্রসেস হচ্ছে, কিছুক্ষণের মধ্যেই সম্পন্ন হয়ে যাবে এবং আপনাকে জানানো হবে।"
        )
    else:
        text = (
            "✅ <b>আপনার অর্ডার সফলভাবে গ্রহণ করা হয়েছে!</b>\n\n"
            f"🆔 Order ID: <code>{order.order_code}</code>\n"
            f"🎮 Player ID: <code>{order.player_id}</code>\n"
            f"🟡 Status: Pending Delivery\n\n"
            "কিছুক্ষণের মধ্যে top-up হয়ে যাবে, আপনাকে নোটিফাই করা হবে।"
        )
    await call.message.edit_text(text, reply_markup=_NO_INLINE)
    await call.answer("✅ Order placed!")

    if not is_auto:
        for admin_id in ADMIN_IDS:
            try:
                await call.bot.send_message(
                    admin_id,
                    f"🔔 <b>New Top-up Order (Manual)</b>\n\n"
                    f"🆔 {order.order_code}\n"
                    f"👤 {call.from_user.first_name} (<code>{call.from_user.id}</code>)\n"
                    f"💎 {order.package_name_snapshot}\n"
                    f"🎮 Player ID: <code>{order.player_id}</code>\n"
                    f"🌍 Server: {SERVER_LABEL}\n"
                    f"💰 {fmt_money(order.price_paid)}",
                )
            except Exception:
                pass


async def _render_orders_page(session, user_id: int, page: int):
    result = await session.execute(
        select(Order).where(Order.user_id == user_id)
        .order_by(desc(Order.created_at)).offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)
    )
    orders = result.scalars().all()
    has_next = len(orders) > PAGE_SIZE
    orders = orders[:PAGE_SIZE]
    if not orders and page == 0:
        return "📦 আপনার কোনো অর্ডার নেই।", None
    return "📦 <b>My Orders</b>\n\nদেখতে অর্ডারে ট্যাপ করুন:", orders_list_kb(orders, page, has_next)


@router.callback_query(F.data.startswith("orders:"))
async def cb_my_orders(call: CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(call.data.split(":")[1])
    async with get_session() as session:
        text, kb = await _render_orders_page(session, call.from_user.id, page)
    await call.message.edit_text(text, reply_markup=kb or _NO_INLINE)
    await call.answer()


@router.callback_query(F.data.startswith("order_view:"))
async def cb_order_view(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])
    async with get_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()

        if order is None or order.user_id != call.from_user.id:
            await call.answer("❌ Order not found.", show_alert=True)
            return

        status_map = {
            "PENDING_DELIVERY": "🟡 Pending Delivery",
            "PROCESSING": "⚡ Processing (automatic)",
            "DELIVERED": "🟢 Delivered",
            "CANCELLED": "🔴 Cancelled",
        }
        text = (
            f"📦 <b>Order {order.order_code}</b>\n\n"
            f"💎 Package: {order.package_name_snapshot}\n"
            f"🎮 Player ID: <code>{order.player_id}</code>\n"
            f"💰 Price: {fmt_money(order.price_paid)}\n"
            f"📅 Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"Status: {status_map.get(order.status.value)}"
        )
        if order.delivery_note:
            text += f"\n\n📝 Note: {order.delivery_note}"

    # "⬅️ Back" এখানে ইনলাইন রাখা হয়েছে — কারণ কোন page-এ ছিল সেটা মনে রেখে
    # লিস্টে ফেরত যাওয়া দরকার, Reply Keyboard দিয়ে সেই context বহন করা যায় না।
    await call.message.edit_text(text, reply_markup=back_home("orders:0"))
    await call.answer()
