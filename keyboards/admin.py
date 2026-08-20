from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CURRENCY

ADMIN_MENU_LABELS = {
    "dashboard": "📊 Dashboard",
    "users": "👥 Users",
    "packages": "💎 Packages",
    "providers": "🔌 API Providers",
    "orders": "📦 Orders",
    "deposits": "💰 Deposit Requests",
    "payment_methods": "💳 Payment Methods",
    "referral": "🎁 Referral Settings",
    "mraipay": "💳 Auto Payment (Mr Ai Pay)",
    "broadcast": "📢 Broadcast",
    "logs": "📝 Activity Logs",
    "exit": "❌ Exit Admin Panel",
}


def admin_reply_kb() -> ReplyKeyboardMarkup:
    L = ADMIN_MENU_LABELS
    keyboard = [
        [KeyboardButton(text=L["dashboard"]), KeyboardButton(text=L["users"])],
        [KeyboardButton(text=L["packages"]), KeyboardButton(text=L["providers"])],
        [KeyboardButton(text=L["orders"]), KeyboardButton(text=L["deposits"])],
        [KeyboardButton(text=L["payment_methods"]), KeyboardButton(text=L["referral"])],
        [KeyboardButton(text=L["mraipay"]), KeyboardButton(text=L["broadcast"])],
        [KeyboardButton(text=L["logs"])],
        [KeyboardButton(text=L["exit"])],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)


def admin_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Dashboard", callback_data="adm:dash")
    b.button(text="👥 Users", callback_data="adm:users:0")
    b.button(text="💎 Packages", callback_data="adm:pkgs")
    b.button(text="🔌 API Providers", callback_data="adm:providers")
    b.button(text="📦 Orders", callback_data="adm:orders:0")
    b.button(text="💰 Deposit Requests", callback_data="adm:deps:0")
    b.button(text="💳 Payment Methods", callback_data="adm:pms")
    b.button(text="🎁 Referral Settings", callback_data="adm:refset")
    b.button(text="💳 Auto Payment (Mr Ai Pay)", callback_data="adm:mraipay")
    b.button(text="📢 Broadcast", callback_data="adm:broadcast")
    b.button(text="📝 Activity Logs", callback_data="adm:logs:0")
    b.adjust(1, 2, 2, 2, 2, 1, 1)
    return b.as_markup()


def admin_provider_type_kb() -> InlineKeyboardMarkup:
    from services.api_client import PROVIDER_TYPES
    b = InlineKeyboardBuilder()
    for key, label in PROVIDER_TYPES.items():
        b.button(text=label, callback_data=f"adm:prov_type:{key}")
    b.adjust(1)
    return b.as_markup()


def admin_providers_kb(providers) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in providers:
        status = "🟢" if p.is_active else "🔴"
        type_tag = "⚡" if p.provider_type == "EPINBY" else "🔧"
        b.button(text=f"{status} {type_tag} {p.name} ({p.currency})", callback_data=f"adm:prov:{p.id}")
    b.button(text="➕ Add Provider", callback_data="adm:prov_add")
    b.button(text="⬅️ Back", callback_data="adm:home")
    b.adjust(1)
    return b.as_markup()


def admin_provider_detail_kb(provider) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🧪 Test Connection", callback_data=f"adm:prov_test:{provider.id}")
    if provider.is_active:
        b.button(text="🔴 Disable", callback_data=f"adm:prov_toggle:{provider.id}")
    else:
        b.button(text="🟢 Enable", callback_data=f"adm:prov_toggle:{provider.id}")
    b.button(text="🗑️ Delete", callback_data=f"adm:prov_del:{provider.id}")
    b.button(text="⬅️ Back", callback_data="adm:providers")
    b.adjust(1, 2, 1)
    return b.as_markup()


def admin_pkg_delivery_choice_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚡ Automatic (API Provider)", callback_data="adm:pkg_mode_auto")
    b.button(text="✍️ Manual (Admin delivers)", callback_data="adm:pkg_mode_manual")
    b.adjust(1)
    return b.as_markup()


def admin_pkg_provider_choice_kb(providers) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in providers:
        b.button(text=f"🔌 {p.name}", callback_data=f"adm:pkg_provider:{p.id}")
    b.adjust(1)
    return b.as_markup()


def admin_back(cb: str = "adm:home") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Back", callback_data=cb)
    return b.as_markup()


def admin_packages_kb(packages) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in packages:
        status = "🟢" if p.is_active else "🔴"
        b.button(text=f"{status} {p.name} ({CURRENCY}{p.price})", callback_data=f"adm:pkg:{p.id}")
    b.button(text="➕ Add Package", callback_data="adm:pkg_add")
    b.button(text="⬅️ Back", callback_data="adm:home")
    b.adjust(1)
    return b.as_markup()


def admin_package_detail_kb(pkg) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if pkg.is_active:
        b.button(text="🔴 Deactivate", callback_data=f"adm:pkg_toggle:{pkg.id}")
    else:
        b.button(text="🟢 Activate", callback_data=f"adm:pkg_toggle:{pkg.id}")
    b.button(text="🗑️ Delete", callback_data=f"adm:pkg_del:{pkg.id}")
    b.button(text="⬅️ Back", callback_data="adm:pkgs")
    b.adjust(2, 1)
    return b.as_markup()


def admin_orders_kb(orders, page: int, has_next: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for o in orders:
        status_emoji = {"PENDING_DELIVERY": "🟡", "PROCESSING": "⚡", "DELIVERED": "🟢", "CANCELLED": "🔴"}.get(o.status.value, "⚪")
        b.button(text=f"{status_emoji} {o.order_code} — {o.player_id}", callback_data=f"adm:order:{o.id}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"adm:orders:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"adm:orders:{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="adm:home"))
    return b.as_markup()


def admin_order_detail_kb(order) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if order.status.value in ("PENDING_DELIVERY", "PROCESSING"):
        b.button(text="✅ Mark Delivered", callback_data=f"adm:deliver:{order.id}")
        b.button(text="📝 Add Delivery Note", callback_data=f"adm:deliver_note:{order.id}")
        b.button(text="❌ Cancel & Refund", callback_data=f"adm:order_cancel:{order.id}")
    b.button(text="⬅️ Back", callback_data="adm:orders:0")
    b.adjust(1)
    return b.as_markup()


def admin_deposits_kb(deposits, page: int, has_next: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in deposits:
        status_emoji = {"PENDING": "🟡", "APPROVED": "🟢", "REJECTED": "🔴"}.get(d.status.value, "⚪")
        b.button(text=f"{status_emoji} #{d.id} - {CURRENCY}{d.amount}", callback_data=f"adm:dep:{d.id}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"adm:deps:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"adm:deps:{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="adm:home"))
    return b.as_markup()


def admin_deposit_detail_kb(deposit) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if deposit.status.value == "PENDING":
        b.button(text="✅ Approve", callback_data=f"adm:dep_approve:{deposit.id}")
        b.button(text="❌ Reject", callback_data=f"adm:dep_reject:{deposit.id}")
    b.button(text="⬅️ Back", callback_data="adm:deps:0")
    b.adjust(2, 1)
    return b.as_markup()


def admin_users_kb(users, page: int, has_next: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        label = f"{'🚫' if u.is_banned else '👤'} {u.first_name or u.id} ({CURRENCY}{u.balance})"
        b.button(text=label, callback_data=f"adm:user:{u.id}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"adm:users:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"adm:users:{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="adm:home"))
    return b.as_markup()


def admin_user_detail_kb(user) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 Add Balance", callback_data=f"adm:bal_add:{user.id}")
    b.button(text="💸 Deduct Balance", callback_data=f"adm:bal_deduct:{user.id}")
    if user.is_banned:
        b.button(text="✅ Unban", callback_data=f"adm:unban:{user.id}")
    else:
        b.button(text="🚫 Ban", callback_data=f"adm:ban:{user.id}")
    b.button(text="⬅️ Back", callback_data="adm:users:0")
    b.adjust(2, 1, 1)
    return b.as_markup()


def admin_payment_methods_kb(methods) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in methods:
        status = "🟢" if m.is_active else "🔴"
        b.button(text=f"{status} {m.method_name}", callback_data=f"adm:pm:{m.id}")
    b.button(text="➕ Add Payment Method", callback_data="adm:pm_add")
    b.button(text="⬅️ Back", callback_data="adm:home")
    b.adjust(1)
    return b.as_markup()


def admin_pm_detail_kb(pm) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if pm.is_active:
        b.button(text="🔴 Disable", callback_data=f"adm:pm_toggle:{pm.id}")
    else:
        b.button(text="🟢 Enable", callback_data=f"adm:pm_toggle:{pm.id}")
    b.button(text="🗑️ Delete", callback_data=f"adm:pm_del:{pm.id}")
    b.button(text="⬅️ Back", callback_data="adm:pms")
    b.adjust(2, 1)
    return b.as_markup()


def admin_referral_settings_kb(enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=("🔴 Disable Bonus" if enabled else "🟢 Enable Bonus"), callback_data="adm:refset_toggle")
    b.button(text="✏️ Set Bonus Amount", callback_data="adm:refset_amount")
    b.button(text="⬅️ Back", callback_data="adm:home")
    b.adjust(1)
    return b.as_markup()


def admin_mraipay_kb(enabled: bool, configured: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔑 Set API Key", callback_data="adm:mraipay_key")
    b.button(text="🔐 Set Secret Key", callback_data="adm:mraipay_secret")
    b.button(text="🏷️ Set Brand Key", callback_data="adm:mraipay_brand")
    if configured:
        b.button(text=("🔴 Disable" if enabled else "🟢 Enable"), callback_data="adm:mraipay_toggle")
    b.button(text="⬅️ Back", callback_data="adm:home")
    b.adjust(1)
    return b.as_markup()
