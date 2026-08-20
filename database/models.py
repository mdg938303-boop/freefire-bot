"""
Database models. Empty by default — no diamond packages exist until the
Admin creates them via the Admin Panel.
"""
from __future__ import annotations

import enum
import secrets
import string
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def gen_order_id() -> str:
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    return f"FF-{suffix}"


class OrderStatus(str, enum.Enum):
    PENDING_DELIVERY = "PENDING_DELIVERY"   # manual fulfillment, awaiting admin
    PROCESSING = "PROCESSING"                # dispatched to provider API, awaiting completion
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DepositStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TransactionType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    REFERRAL_BONUS = "REFERRAL_BONUS"
    ADJUSTMENT = "ADJUSTMENT"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_deposit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_spent: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    referral_earnings: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    referral_code: Mapped[str] = mapped_column(String(32), unique=True)
    referred_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    # Remembered so returning customers don't have to retype their Player ID
    last_player_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class ApiProvider(Base):
    """A diamond top-up API reseller/provider. Empty by default."""
    __tablename__ = "api_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    # "EPINBY" (REST JSON, X-API-KEY header) or "SMM_GENERIC" (form-data action=add/status/balance)
    provider_type: Mapped[str] = mapped_column(String(32), default="SMM_GENERIC")
    base_url: Mapped[str] = mapped_column(String(256))
    api_key: Mapped[str] = mapped_column(String(256))
    api_secret: Mapped[str | None] = mapped_column(String(256), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    packages: Mapped[list["Package"]] = relationship(back_populates="api_provider")


class Package(Base):
    """A diamond top-up package, e.g. '100 Diamond — ৳95'. Empty by default."""
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))          # e.g. "100 Diamond"
    diamond_amount: Mapped[str] = mapped_column(String(32))  # free text: "100", "Weekly Membership" etc
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # If both are set, orders for this package are delivered AUTOMATICALLY via
    # the provider's API. If either is null, the package falls back to MANUAL
    # admin delivery (the original workflow).
    api_provider_id: Mapped[int | None] = mapped_column(ForeignKey("api_providers.id"), nullable=True)
    api_service_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)  # provider's rate, for margin reference

    api_provider: Mapped["ApiProvider | None"] = relationship(back_populates="packages")
    orders: Mapped[list["Order"]] = relationship(back_populates="package")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(32), unique=True, default=gen_order_id)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"))

    package_name_snapshot: Mapped[str] = mapped_column(String(128))
    price_paid: Mapped[float] = mapped_column(Numeric(12, 2))

    # The player-supplied Free Fire UID — NOT sensitive, stored in plaintext.
    player_id: Mapped[str] = mapped_column(String(32))

    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING_DELIVERY)
    delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Populated only for API-fulfilled orders (see services/order_sync.py)
    api_provider_id: Mapped[int | None] = mapped_column(ForeignKey("api_providers.id"), nullable=True)
    api_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    api_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_api_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")
    package: Mapped["Package"] = relationship(back_populates="orders")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    method_name: Mapped[str] = mapped_column(String(64))
    account_number: Mapped[str] = mapped_column(String(64))
    account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    deposits: Mapped[list["Deposit"]] = relationship(back_populates="method")


class Deposit(Base):
    __tablename__ = "deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    method_id: Mapped[int] = mapped_column(ForeignKey("payment_methods.id"))

    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    transaction_id: Mapped[str] = mapped_column(String(128))
    sender_number: Mapped[str] = mapped_column(String(32))

    status: Mapped[DepositStatus] = mapped_column(Enum(DepositStatus), default=DepositStatus.PENDING)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()
    method: Mapped["PaymentMethod"] = relationship(back_populates="deposits")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship()


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    referred_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), unique=True)
    bonus_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AutoDeposit(Base):
    """Mr Ai Pay গেটওয়ে দিয়ে সফলভাবে verify হওয়া প্রতিটা payment-এর রেকর্ড —
    transaction_id দিয়ে idempotency guard করা হয় (একই payment দুইবার credit
    যেন না হয়)।"""
    __tablename__ = "auto_deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    transaction_id: Mapped[str] = mapped_column(String(128), unique=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(128))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
