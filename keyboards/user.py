from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CURRENCY

# ----------------------------------------------------------------------
# রিপ্লাই কিবোর্ড (নিচে সবসময় visible, স্ক্রিন বদলালেও থাকে) — মূল নেভিগেশনের
# জন্য এটাই ব্যবহার হয়, ইনলাইন বাটন শুধু তখনই যেখানে item-নির্দিষ্ট (dynamic ID
# লুকানো, যেমন package/order/provider সিলেকশন, pagination) ছাড়া উপায় নেই।
# ----------------------------------------------------------------------

MAIN_MENU_LABELS = {
    "home": "🏠 Home",
    "topup": "💎 Top-up করুন",
    "uid_check": "🔍 UID Check",
    "wallet": "💰 Wallet",
    "deposit": "➕ Deposit",
    "orders": "📦 My Orders",
    "referral": "🎁 Referral",
    "profile": "👤 Profile",
    "txns": "📜 Transaction History",
    "help": "❓ Help / Support",
}


def main_reply_kb() -> ReplyKeyboardMarkup:
    L = MAIN_MENU_LABELS
    keyboard = [
        [KeyboardButton(text=L["home"]), KeyboardButton(text=L["topup"])],
        [KeyboardButton(text=L["uid_check"]), KeyboardButton(text=L["wallet"])],
        [KeyboardButton(text=L["deposit"]), KeyboardButton(text=L["orders"])],
        [KeyboardButton(text=L["referral"]), KeyboardButton(text=L["profile"])],
        [KeyboardButton(text=L["txns"]), KeyboardButton(text=L["help"])],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)


def back_home(back_cb: str | None = None) -> InlineKeyboardMarkup | None:
    """
    শুধু নির্দিষ্ট একটা আগের screen-এ (যেমন page 2 থেকে page 1) ফিরতে হলে
    back_cb দিন — তখন একটা ছোট্ট ইনলাইন "⬅️ Back" বাটন দেখাবে (এটা প্রয়োজনীয়,
    কারণ কোন page-এ ছিলেন সেটা রিপ্লাই কিবোর্ড মনে রাখতে পারে না)।
    কিছু না দিলে কোনো ইনলাইন বাটন দেখাবে না — নিচের persistent রিপ্লাই কিবোর্ডেই
    Home বাটন সবসময় থাকে, তাই আলাদা ইনলাইন "Home" দরকার নেই।
    """
    if not back_cb:
        return None
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Back", callback_data=back_cb)
    return b.as_markup()


def packages_kb(packages) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in packages:
        b.button(text=f"💎 {p.name} — {CURRENCY}{p.price}", callback_data=f"pkg:{p.id}")
    b.adjust(1)
    return b.as_markup()


def package_detail_kb(pkg_id: int, has_saved_id: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_saved_id:
        b.button(text="✅ আগের Player ID ব্যবহার করুন", callback_data=f"pkg_use_saved:{pkg_id}")
    b.button(text="✏️ Player ID লিখুন", callback_data=f"pkg_enter_id:{pkg_id}")
    b.button(text="❌ Cancel", callback_data="topup_menu")
    b.adjust(1)
    return b.as_markup()


def order_final_confirm_kb(pkg_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ হ্যাঁ, ID সঠিক আছে — Confirm Purchase", callback_data=f"order_place:{pkg_id}")
    b.button(text="✏️ ID পরিবর্তন করুন", callback_data=f"pkg_enter_id:{pkg_id}")
    b.button(text="❌ Cancel", callback_data="topup_menu")
    b.adjust(1)
    return b.as_markup()


def cancel_kb(back_cb: str = "home") -> InlineKeyboardMarkup:
    """মাল্টি-স্টেপ ফর্মের (deposit amount/txn id ইত্যাদি টাইপ করার) মাঝপথে
    এক-ট্যাপে বাতিল করার জন্য — এটা টাইপ করে /cancel লেখার চেয়ে অনেক সহজ,
    তাই এখানে ইনলাইন রাখাই যুক্তিসঙ্গত।"""
    b = InlineKeyboardBuilder()
    b.button(text="❌ Cancel", callback_data=back_cb)
    return b.as_markup()


def deposit_choice_kb(auto_available: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if auto_available:
        b.button(text="⚡ Instant (Auto — bKash/Nagad/Rocket)", callback_data="dep_auto")
    b.button(text="✍️ Manual (bKash/Nagad)", callback_data="dep_manual")
    b.adjust(1)
    return b.as_markup()


def deposit_methods_kb(methods) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in methods:
        b.button(text=f"💳 {m.method_name}", callback_data=f"dep_method:{m.id}")
    b.adjust(1)
    return b.as_markup()


def orders_list_kb(orders, page: int, has_next: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for o in orders:
        status_emoji = {"PENDING_DELIVERY": "🟡", "PROCESSING": "⚡", "DELIVERED": "🟢", "CANCELLED": "🔴"}.get(o.status.value, "⚪")
        b.button(text=f"{status_emoji} {o.order_code}", callback_data=f"order_view:{o.id}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"orders:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"orders:{page+1}"))
    if nav:
        b.row(*nav)
    return b.as_markup()


def txns_list_kb(page: int, has_next: bool) -> InlineKeyboardMarkup | None:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"txns:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"txns:{page+1}"))
    if not nav:
        return None
    b = InlineKeyboardBuilder()
    b.row(*nav)
    return b.as_markup()
