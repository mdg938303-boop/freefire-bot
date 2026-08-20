import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Transaction, TransactionType, User


class InsufficientBalanceError(Exception):
    pass


async def get_or_create_user(session: AsyncSession, tg_user) -> User:
    result = await session.execute(select(User).where(User.id == tg_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name,
            referral_code=secrets.token_urlsafe(6),
        )
        session.add(user)
        await session.flush()
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
    return user


async def credit(session: AsyncSession, user: User, amount: float, txn_type: TransactionType, note: str | None = None) -> Transaction:
    user.balance = float(user.balance) + float(amount)
    if txn_type == TransactionType.DEPOSIT:
        user.total_deposit = float(user.total_deposit) + float(amount)
    elif txn_type == TransactionType.REFERRAL_BONUS:
        user.referral_earnings = float(user.referral_earnings) + float(amount)
    txn = Transaction(user_id=user.id, type=txn_type, amount=amount, note=note)
    session.add(txn)
    await session.flush()
    return txn


async def debit(session: AsyncSession, user: User, amount: float, txn_type: TransactionType, note: str | None = None) -> Transaction:
    if float(user.balance) < float(amount):
        raise InsufficientBalanceError()
    user.balance = float(user.balance) - float(amount)
    if txn_type == TransactionType.PURCHASE:
        user.total_spent = float(user.total_spent) + float(amount)
    txn = Transaction(user_id=user.id, type=txn_type, amount=amount, note=note)
    session.add(txn)
    await session.flush()
    return txn
