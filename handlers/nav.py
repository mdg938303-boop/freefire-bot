"""
মূল নেভিগেশন বাটনগুলোর (Reply Keyboard-এ নিচে সবসময় visible) সব হ্যান্ডলার এখানে,
একটা আলাদা router-এ যেটা main.py-তে **সবার আগে** include করা হয়।

এটা ইচ্ছাকৃতভাবে আলাদা করা হয়েছে যাতে কেউ যদি কোনো multi-step ফর্মের মাঝখানে
(deposit amount, transaction ID, player UID টাইপ করার সময়) হঠাৎ "🏠 Home" বা
অন্য কোনো মেনু বাটনে চেপে বসে, সেটা সবসময় সঠিকভাবে সেই ফর্ম থেকে বের করে
নিয়ে আসবে — অন্য কোনো router-এর "বর্তমান state-এ যেকোনো টেক্সট গ্রহণ করবে" টাইপ
হ্যান্ডলার (যেমন deposit amount input) কখনো এই বাটনগুলোকে "hijack" করতে পারবে না।
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database.database import get_session
from keyboards.admin import ADMIN_MENU_LABELS
from keyboards.user import MAIN_MENU_LABELS
from services.wallet import get_or_create_user

router = Router(name="nav")


@router.message(F.text == MAIN_MENU_LABELS["home"])
async def nav_home(message: Message, state: FSMContext):
    from handlers.user import render_home

    await state.clear()
    async with get_session() as session:
        user = await get_or_create_user(session, message.from_user)
        await session.commit()
        text = await render_home(session, user)
    await message.answer(text)


@router.message(F.text == MAIN_MENU_LABELS["profile"])
async def nav_profile(message: Message, state: FSMContext):
    from handlers.user import _profile_text

    await state.clear()
    async with get_session() as session:
        user = await get_or_create_user(session, message.from_user)
        await session.commit()
    await message.answer(_profile_text(user))


@router.message(F.text == MAIN_MENU_LABELS["wallet"])
async def nav_wallet(message: Message, state: FSMContext):
    from handlers.user import _wallet_text

    await state.clear()
    async with get_session() as session:
        user = await get_or_create_user(session, message.from_user)
        await session.commit()
    await message.answer(_wallet_text(user))


@router.message(F.text == MAIN_MENU_LABELS["help"])
async def nav_help(message: Message, state: FSMContext):
    from config import SUPPORT_USERNAME

    await state.clear()
    await message.answer(f"❓ <b>Help / Support</b>\n\nযেকোনো সমস্যায় যোগাযোগ করুন: {SUPPORT_USERNAME}")


@router.message(F.text == MAIN_MENU_LABELS["topup"])
async def nav_topup_menu(message: Message, state: FSMContext):
    from handlers.user import _render_topup_menu

    await state.clear()
    async with get_session() as session:
        text, kb = await _render_topup_menu(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == MAIN_MENU_LABELS["uid_check"])
async def nav_uid_check(message: Message, state: FSMContext):
    from utils.states import UidCheckFlow
    from handlers.user import _find_epinby_lookup_package

    await state.clear()
    async with get_session() as session:
        row = await _find_epinby_lookup_package(session)

    if row is None:
        await message.answer("🔍 এই মুহূর্তে UID Check ফিচারটি সেটআপ করা নেই। সাপোর্টে যোগাযোগ করুন।")
        return

    await state.set_state(UidCheckFlow.waiting_uid)
    await message.answer(
        "🔍 <b>UID Check</b>\n\n"
        "যেই Free Fire Player ID (UID)-এর in-game নাম দেখতে চান, সেটা লিখে পাঠান:",
    )


@router.message(F.text == MAIN_MENU_LABELS["deposit"])
async def nav_deposit(message: Message, state: FSMContext):
    from handlers.deposit import _render_deposit_choice

    await state.clear()
    async with get_session() as session:
        text, kb = await _render_deposit_choice(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == MAIN_MENU_LABELS["orders"])
async def nav_my_orders(message: Message, state: FSMContext):
    from handlers.orders import _render_orders_page

    await state.clear()
    async with get_session() as session:
        text, kb = await _render_orders_page(session, message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == MAIN_MENU_LABELS["referral"])
async def nav_referral(message: Message, state: FSMContext):
    from handlers.referral import _render_referral_text

    await state.clear()
    async with get_session() as session:
        text = await _render_referral_text(message.bot, session, message.from_user)
    await message.answer(text)


@router.message(F.text == MAIN_MENU_LABELS["txns"])
async def nav_transactions(message: Message, state: FSMContext):
    from handlers.referral import _render_txns_page

    await state.clear()
    async with get_session() as session:
        text, kb = await _render_txns_page(session, message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


# ---------------- Admin Reply Keyboard নেভিগেশন ----------------
# এগুলোও সর্বোচ্চ অগ্রাধিকার router-এ, একই কারণে (কোনো ফর্মের মাঝে hijack না হয়)।
# প্রতিটাতে _is_admin() চেক করা হয় যাতে সাধারণ ইউজার ভুলবশত এই লেবেলগুলোর
# কোনোটা টাইপ করলেও কিছু না হয়।

@router.message(F.text == ADMIN_MENU_LABELS["dashboard"])
async def nav_admin_dashboard(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_dashboard

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_dashboard(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["users"])
async def nav_admin_users(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_users

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_users(session, 0)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["packages"])
async def nav_admin_packages(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_packages

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_packages(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["providers"])
async def nav_admin_providers(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_providers

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_providers(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["orders"])
async def nav_admin_orders(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_orders

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_orders(session, 0)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["deposits"])
async def nav_admin_deposits(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_deposits

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_deposits(session, 0)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["payment_methods"])
async def nav_admin_payment_methods(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_payment_methods

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_payment_methods(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["referral"])
async def nav_admin_referral(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_refset

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_refset(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["mraipay"])
async def nav_admin_mraipay(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_mraipay

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_mraipay(session)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["broadcast"])
async def nav_admin_broadcast(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from utils.states import AdminBroadcastFlow

    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminBroadcastFlow.waiting_message)
    await message.answer("📢 <b>Broadcast</b>\n\nসব User-কে যে message পাঠাতে চান তা লিখুন:")


@router.message(F.text == ADMIN_MENU_LABELS["logs"])
async def nav_admin_logs(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from handlers.admin import _render_logs

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_logs(session, 0)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == ADMIN_MENU_LABELS["exit"])
async def nav_admin_exit(message: Message, state: FSMContext):
    from utils.helpers import is_admin
    from keyboards.user import main_reply_kb

    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("✅ Admin Panel থেকে বের হওয়া হলো।", reply_markup=main_reply_kb())
