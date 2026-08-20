from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select

from config import ADMIN_IDS, PUBLIC_BASE_URL
from database.database import get_session
from database.models import PaymentMethod
from keyboards.user import cancel_kb, deposit_choice_kb, deposit_methods_kb
from services.mraipay_client import MrAiPayClient, MrAiPayError
from services.payments import create_deposit_request, get_mraipay_config
from services.wallet import get_or_create_user
from utils.helpers import fmt_money
from utils.states import AutoDepositFlow, DepositFlow

router = Router(name="deposit")

_NO_INLINE = InlineKeyboardMarkup(inline_keyboard=[])


# ---------------- এন্ট্রি — Auto vs Manual বেছে নেওয়া ----------------

async def _render_deposit_choice(session):
    config = await get_mraipay_config(session)
    return "💰 <b>কীভাবে Deposit করতে চান?</b>", deposit_choice_kb(auto_available=config is not None)


@router.callback_query(F.data == "deposit")
async def cb_deposit_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_deposit_choice(session)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# ---------------- ⚡ AUTO (Mr Ai Pay — bKash/Nagad/Rocket) ----------------

@router.callback_query(F.data == "dep_auto")
async def cb_dep_auto(call: CallbackQuery, state: FSMContext):
    async with get_session() as session:
        config = await get_mraipay_config(session)

    if config is None or not PUBLIC_BASE_URL:
        await call.answer("⚡ এই মুহূর্তে Auto Deposit available নেই।", show_alert=True)
        return

    await state.set_state(AutoDepositFlow.waiting_amount)
    await call.message.edit_text(
        "⚡ <b>Instant Deposit</b>\n\nআপনি কত টাকা Deposit করতে চান?\n\n(শুধু সংখ্যা লিখুন, যেমন: 500)",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(AutoDepositFlow.waiting_amount)
async def auto_deposit_amount_entered(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ সঠিক পরিমাণ লিখুন (শুধু সংখ্যা, ০ এর বেশি)।")
        return

    async with get_session() as session:
        config = await get_mraipay_config(session)
        user = await get_or_create_user(session, message.from_user)
        await session.commit()

    if config is None or not PUBLIC_BASE_URL:
        await message.answer("⚡ এই মুহূর্তে Auto Deposit available নেই। Manual দিয়ে ট্রাই করুন।")
        await state.clear()
        return

    wait_msg = await message.answer("⏳ Payment link তৈরি করা হচ্ছে...")

    client = MrAiPayClient(config["api_key"], config["secret_key"], config["brand_key"])
    try:
        payment_url = await client.create_payment(
            amount=amount,
            cus_name=message.from_user.first_name or "Customer",
            cus_email=f"user{user.id}@telegram.local",
            success_url=f"{PUBLIC_BASE_URL}/payment/success",
            cancel_url=f"{PUBLIC_BASE_URL}/payment/cancel",
            metadata={"tg_user_id": user.id},
        )
    except MrAiPayError as exc:
        await wait_msg.edit_text(f"❌ Payment link তৈরি করা যায়নি: {exc}\n\nএকটু পরে আবার চেষ্টা করুন।")
        await state.clear()
        return

    await state.clear()
    from aiogram.types import WebAppInfo
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="💳 Pay Now", web_app=WebAppInfo(url=payment_url))
    b.adjust(1)
    await wait_msg.edit_text(
        f"⚡ <b>Instant Deposit</b>\n\n💰 Amount: {fmt_money(amount)}\n\n"
        "নিচের বাটনে চেপে bKash/Nagad/Rocket দিয়ে পে করুন। পেমেন্ট সম্পন্ন হলে "
        "আপনার ব্যালেন্স <b>স্বয়ংক্রিয়ভাবে</b> যোগ হয়ে যাবে এবং একটা নিশ্চিতকরণ মেসেজ পাবেন।",
        reply_markup=b.as_markup(),
    )


# ---------------- ✍️ MANUAL (আগের সিস্টেম) ----------------

async def _render_deposit_methods(session):
    result = await session.execute(select(PaymentMethod).where(PaymentMethod.is_active == True))  # noqa: E712
    methods = result.scalars().all()
    if not methods:
        return "💰 বর্তমানে কোনো Deposit Method available নেই। সাপোর্টে যোগাযোগ করুন।", None
    return "✍️ <b>Select Deposit Method:</b>", deposit_methods_kb(methods)


@router.callback_query(F.data == "dep_manual")
async def cb_dep_manual(call: CallbackQuery, state: FSMContext):
    await state.clear()
    async with get_session() as session:
        text, kb = await _render_deposit_methods(session)
    await call.message.edit_text(text, reply_markup=kb or _NO_INLINE)
    await call.answer()


@router.callback_query(F.data.startswith("dep_method:"))
async def cb_deposit_method_selected(call: CallbackQuery, state: FSMContext):
    method_id = int(call.data.split(":")[1])
    async with get_session() as session:
        result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == method_id))
        method = result.scalar_one_or_none()

    if method is None or not method.is_active:
        await call.answer("❌ এই method টি আর available নেই।", show_alert=True)
        return

    await state.update_data(method_id=method_id, method_name=method.method_name)
    await state.set_state(DepositFlow.waiting_amount)
    await call.message.edit_text(
        "আপনি কত টাকা Deposit করতে চান?\n\n(শুধু সংখ্যা লিখুন, যেমন: 500)",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(DepositFlow.waiting_amount)
async def deposit_amount_entered(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ সঠিক পরিমাণ লিখুন (শুধু সংখ্যা, ০ এর বেশি)।")
        return

    data = await state.get_data()
    async with get_session() as session:
        result = await session.execute(select(PaymentMethod).where(PaymentMethod.id == data["method_id"]))
        method = result.scalar_one_or_none()

    if method is None:
        await message.answer("❌ Method not found. আবার শুরু করুন।")
        await state.clear()
        return

    await state.update_data(amount=amount)
    await state.set_state(DepositFlow.waiting_txn_id)
    await message.answer(
        f"💰 Amount: {fmt_money(amount)}\n\n"
        f"📱 Send Money to ({method.method_name}):\n<code>{method.account_number}</code>\n\n"
        f"{method.instructions or ''}\n\n"
        "টাকা পাঠানোর পর, <b>Transaction ID</b> লিখে পাঠান:",
        reply_markup=cancel_kb(),
    )


@router.message(DepositFlow.waiting_txn_id)
async def deposit_txn_id_entered(message: Message, state: FSMContext):
    txn_id = message.text.strip()
    if not txn_id:
        await message.answer("⚠️ Transaction ID লিখুন।")
        return
    await state.update_data(transaction_id=txn_id)
    await state.set_state(DepositFlow.waiting_sender_number)
    await message.answer("📱 আপনার Sender Mobile Number লিখুন:", reply_markup=cancel_kb())


@router.message(DepositFlow.waiting_sender_number)
async def deposit_sender_number_entered(message: Message, state: FSMContext):
    sender_number = message.text.strip()
    if not sender_number:
        await message.answer("⚠️ Sender Mobile Number লিখুন।")
        return

    data = await state.get_data()
    async with get_session() as session:
        user = await get_or_create_user(session, message.from_user)
        await session.commit()
        deposit = await create_deposit_request(
            session, user, data["method_id"], data["amount"], data["transaction_id"], sender_number
        )

    await state.clear()
    await message.answer(
        "✅ <b>Deposit Request তৈরি হয়েছে!</b>\n\n"
        f"💰 Amount: {fmt_money(data['amount'])}\n"
        f"💳 Method: {data['method_name']}\n"
        f"🆔 Transaction ID: {data['transaction_id']}\n\n"
        "🟡 Status: Pending Review\n\n"
        "Admin আপনার deposit রিভিউ করার পর ব্যালেন্স যোগ হবে।",
    )

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                "💰 <b>New Deposit Request</b>\n\n"
                f"👤 {message.from_user.first_name} (<code>{message.from_user.id}</code>)\n"
                f"💳 Method: {data['method_name']}\n"
                f"💰 Amount: {fmt_money(data['amount'])}\n"
                f"🆔 Txn ID: {data['transaction_id']}\n"
                f"📱 Sender: {sender_number}\n\n"
                f"Review via Admin Panel → 💰 Deposit Requests → #{deposit.id}",
            )
        except Exception:
            pass
