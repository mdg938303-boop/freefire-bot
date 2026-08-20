from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AutoDeposit, Deposit, DepositStatus, Referral, Setting, TransactionType, User
from services.wallet import credit


async def get_setting(session: AsyncSession, key: str, default: str) -> str:
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.flush()


# পুরনো নাম, backward-compatibility-এর জন্য রাখা (নিচে referral bonus লজিক এটাই ব্যবহার করে)
_get_setting = get_setting


async def _maybe_pay_referral_bonus(session: AsyncSession, referred_user: User) -> None:
    if referred_user.referred_by is None:
        return
    enabled = (await _get_setting(session, "referral_bonus_enabled", "true")) == "true"
    if not enabled:
        return
    existing = await session.execute(select(Referral).where(Referral.referred_id == referred_user.id))
    if existing.scalar_one_or_none() is not None:
        return
    bonus_amount = float(await _get_setting(session, "referral_bonus_amount", "10"))
    if bonus_amount <= 0:
        return
    referrer_result = await session.execute(select(User).where(User.id == referred_user.referred_by))
    referrer = referrer_result.scalar_one_or_none()
    if referrer is None:
        return
    await credit(session, referrer, bonus_amount, TransactionType.REFERRAL_BONUS, note=f"Referral bonus for {referred_user.id}")
    session.add(Referral(referrer_id=referrer.id, referred_id=referred_user.id, bonus_amount=bonus_amount))
    await session.flush()


async def create_deposit_request(session: AsyncSession, user: User, method_id: int, amount: float, transaction_id: str, sender_number: str) -> Deposit:
    deposit = Deposit(
        user_id=user.id, method_id=method_id, amount=amount,
        transaction_id=transaction_id, sender_number=sender_number, status=DepositStatus.PENDING,
    )
    session.add(deposit)
    await session.commit()
    await session.refresh(deposit)
    return deposit


async def approve_deposit(session: AsyncSession, deposit: Deposit) -> None:
    result = await session.execute(select(User).where(User.id == deposit.user_id))
    user = result.scalar_one()
    await credit(session, user, float(deposit.amount), TransactionType.DEPOSIT, note=f"Deposit approved ({deposit.transaction_id})")
    deposit.status = DepositStatus.APPROVED
    deposit.reviewed_at = datetime.utcnow()
    await _maybe_pay_referral_bonus(session, user)
    await session.commit()


async def reject_deposit(session: AsyncSession, deposit: Deposit, reason: str | None = None) -> None:
    deposit.status = DepositStatus.REJECTED
    deposit.rejection_reason = reason
    deposit.reviewed_at = datetime.utcnow()
    await session.commit()


# ----------------------------------------------------------------------
# MR AI PAY — automated bKash/Nagad/Rocket gateway
# ----------------------------------------------------------------------

async def get_mraipay_config(session: AsyncSession) -> dict | None:
    """Enabled + সব key সেট থাকলেই config ফেরত দেয়, নাহলে None (ফিচার বন্ধ থাকবে)।"""
    enabled = (await get_setting(session, "mraipay_enabled", "false")) == "true"
    if not enabled:
        return None
    api_key = await get_setting(session, "mraipay_api_key", "")
    secret_key = await get_setting(session, "mraipay_secret_key", "")
    brand_key = await get_setting(session, "mraipay_brand_key", "")
    if not (api_key and secret_key and brand_key):
        return None
    return {"api_key": api_key, "secret_key": secret_key, "brand_key": brand_key}


async def record_auto_deposit_if_new(
    session: AsyncSession, user: User, transaction_id: str, amount: float,
    payment_method: str | None, status: str,
) -> bool:
    """
    idempotency guard — একই transaction_id দিয়ে দ্বিতীয়বার callback এলে (যেমন
    ইউজার success page reload করলে) আবার credit না হওয়ার নিশ্চয়তা দেয়।
    নতুন হলে credit করে True ফেরত দেয়, আগে থেকে থাকলে False (কিছুই করা হয় না)।
    """
    existing = await session.execute(select(AutoDeposit).where(AutoDeposit.transaction_id == transaction_id))
    if existing.scalar_one_or_none() is not None:
        return False

    record = AutoDeposit(
        user_id=user.id, transaction_id=transaction_id, amount=amount,
        payment_method=payment_method, status=status,
    )
    session.add(record)

    if status == "COMPLETED":
        await credit(session, user, amount, TransactionType.DEPOSIT, note=f"Auto deposit via Mr Ai Pay ({transaction_id})")
        await _maybe_pay_referral_bonus(session, user)

    await session.commit()
    return True
