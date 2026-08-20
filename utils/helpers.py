from config import CURRENCY


def fmt_money(amount) -> str:
    return f"{CURRENCY}{float(amount):,.2f}"


def is_admin(user_id: int) -> bool:
    from config import ADMIN_IDS
    return user_id in ADMIN_IDS
