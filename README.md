# Free Fire Diamond Top-up Bot (Bangladesh Server)

একটা সম্পূর্ণ Telegram bot — Free Fire diamond top-up বিক্রির জন্য, Wallet + Manual
Deposit (bKash/Nagad) + Admin-fulfilled manual delivery মডেলে। VPN/SMM বটের মতোই
architecture (aiogram 3 + async SQLAlchemy), শুরুতে ডাটাবেস সম্পূর্ণ খালি — কোনো
Package আগে থেকে নেই, Admin Panel থেকে তৈরি করতে হবে।

## মূল পার্থক্য (VPN/SMM বট থেকে)

- **একটাই গেম, একটাই সার্ভার** — কোনো category system নেই, শুধু Diamond package লিস্ট
- **Player ID (UID) ক্যাপচার + ডাবল কনফার্মেশন** — ভুল ID-তে টপ-আপ হলে রিফান্ড
  সম্ভব না, তাই অর্ডার করার আগে ইউজারকে তার দেওয়া ID আরেকবার স্পষ্টভাবে দেখিয়ে
  নিশ্চিত করানো হয়
- **Player ID মনে রাখা** — একজন ইউজার দ্বিতীয়বার অর্ডার করলে আগের ID আবার টাইপ না
  করে এক ট্যাপে ব্যবহার করতে পারে
- **API Provider সিস্টেম (SMM বটের মতোই)** — Admin Panel থেকে একটা Diamond
  top-up reseller/provider (API URL + Key + Currency) যোগ করা যায়, প্রতিটা
  Package-কে Provider-এর নিজস্ব Service ID-এর সাথে map করা যায়। যেসব Package
  কোনো Provider-এর সাথে যুক্ত, সেগুলোর অর্ডার **সম্পূর্ণ স্বয়ংক্রিয়ভাবে** API-এর
  মাধ্যমে ডেলিভার হয় — Admin-কে হাত দিতে হয় না। যেসব Package-এ Provider সেট করা
  নেই, সেগুলো আগের মতোই Manual (Admin নিজে top-up করে "Deliver" চাপে)

## অর্ডার প্রসেসিং — দুই মোড

### ⚡ Automatic (API Provider যুক্ত থাকলে)

```
User Confirm করে
   ↓
Provider API-তে অর্ডার পাঠানো হয় (action=add, link=Player ID)
   ↓
API সফল হলে -> Wallet থেকে টাকা কাটা, Order status = PROCESSING
API ব্যর্থ হলে -> কোনো টাকা কাটা হয় না, ইউজার বন্ধুত্বপূর্ণ এরর মেসেজ পায়
   ↓
Background scheduler প্রতি ৬০ সেকেন্ডে Provider-কে status জিজ্ঞেস করে
   ↓
Completed হলে -> Order = DELIVERED, ইউজার notification পায়
Failed/Cancelled হলে -> Wallet-এ Auto-refund, ইউজার notification পায়
```

### ✍️ Manual (Provider সেট করা না থাকলে)

```
User Confirm করে -> Wallet থেকে টাকা কাটা -> Order = PENDING_DELIVERY
   ↓
Admin নিজের top-up panel থেকে ম্যানুয়ালি top-up করে
   ↓
Admin "✅ Mark Delivered" চাপে -> ইউজার notification পায়
```

## API Provider সাপোর্ট

দুই ধরনের provider type সাপোর্ট করে (Admin Panel থেকে যোগ করার সময় বেছে নিতে
হয়):

- **⚡ Epinby** (epinby.com) — আধুনিক REST JSON API, header-based auth। এই
  provider ব্যবহার করলে **Player ID validation** বোনাস ফিচারও কাজ করে —
  অর্ডার কনফার্ম করার আগেই ইউজারকে তার in-game নাম দেখানো হয় (ভুল ID ধরার
  জন্য অতিরিক্ত সুরক্ষা)
- **🔧 Generic SMM Panel** — পুরনো-ধাঁচের form-data API (`action=add/status/balance`),
  বেশিরভাগ BD reseller panel এই ফরম্যাট ব্যবহার করে

ভবিষ্যতে অন্য কোনো ভিন্ন-ফরম্যাটের provider লাগলে `services/api_client.py`-তে
নতুন একটা client ক্লাস (একই `add_order`/`get_status`/`get_balance` মেথড সহ)
যোগ করে `PROVIDER_TYPES` ও `get_provider_client()`-এ বসিয়ে দিলেই চলবে —
বাকি কোডে (`orders.py`, `order_sync.py`) কোনো পরিবর্তন লাগবে না।

## ফোল্ডার স্ট্রাকচার

```
ffbot/
├── main.py                  # entry point (polling লোকাল, webhook Render-এ)
├── config.py                  # env var লোড করে
├── database/
│   ├── models.py                # users, packages, orders (with player_id), deposits...
│   └── database.py                # async engine/session
├── handlers/
│   ├── user.py                     # /start, home, top-up flow + player ID capture
│   ├── orders.py                     # atomic purchase, order history
│   ├── deposit.py                      # manual deposit FSM
│   ├── referral.py                       # referral link + transaction history
│   └── admin.py                            # সম্পূর্ণ Admin Panel
├── keyboards/
│   ├── user.py
│   └── admin.py
├── services/
│   ├── wallet.py                # credit/debit, ledger, কখনো negative না
│   ├── orders.py                  # atomic top-up purchase
│   └── payments.py                  # manual deposit approve/reject + referral bonus
├── utils/
│   ├── helpers.py
│   └── states.py
├── requirements.txt
├── .env.example
└── README.md
```

## ইনস্টলেশন (লোকাল/VPS/Termux)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # BOT_TOKEN, ADMIN_IDS, ইত্যাদি পূরণ করুন
python3 main.py
```

`.env`-এ `DATABASE_URL` ডিফল্ট SQLite (লোকাল টেস্টের জন্য ঠিক আছে)। **Render-এ
deploy করলে অবশ্যই Postgres (Neon.tech ফ্রি টিয়ার) ব্যবহার করুন** — Render-এর ফ্রি
ওয়েব সার্ভিসের ডিস্ক স্থায়ী না, SQLite ফাইল প্রতি restart-এ মুছে যায়।

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | @BotFather থেকে পাওয়া টোকেন |
| `ADMIN_IDS` | ✅ | কমা দিয়ে একাধিক Telegram numeric ID |
| `DATABASE_URL` | — | ডিফল্ট SQLite; Render-এ Postgres (Neon) ব্যবহার করুন |
| `SUPPORT_USERNAME` | — | Help মেনুতে দেখানো হয় |
| `WEBHOOK_BASE_URL` | শুধু Render-ছাড়া webhook host-এ | Render-এ auto (`RENDER_EXTERNAL_URL`) |

## Admin Setup

`/admin` কমান্ড দিলে Admin Panel খুলবে (শুধু `ADMIN_IDS`-এ থাকা ID-দের জন্য কাজ
করবে, অন্যদের জন্য কোনো response নেই)।

## প্রথম Provider ও Package তৈরি

**Provider যোগ করা (Automatic delivery-এর জন্য):**
Admin Panel → 🔌 API Providers → ➕ Add Provider → নাম, Base URL, API Key,
API Secret (না থাকলে "-"), Currency দিন। তারপর 🧪 Test Connection চেপে
balance response আসছে কিনা যাচাই করুন।

Provider-এর নিজস্ব ওয়েবসাইটে লগইন করে "Services" পেজে গিয়ে Free Fire Diamond
top-up service-গুলোর ID খুঁজে বের করুন (SMM প্যানেল টাইপ providerদের প্রায়
সবগুলোই diamond top-up service বিক্রি করে এই একই ফরম্যাটে)।

**Package তৈরি:**
Admin Panel → 💎 Packages → ➕ Add Package → নাম, Diamond পরিমাণ, বিক্রয় মূল্য
দিন। এরপর জিজ্ঞেস করা হবে:
- **⚡ Automatic** বেছে নিলে → Provider সিলেক্ট করুন → Provider-এর Service ID
  দিন → (ঐচ্ছিক) Cost price দিন মার্জিন ট্র্যাক করতে
- **✍️ Manual** বেছে নিলে → সরাসরি তৈরি হয়ে যাবে, Admin নিজে top-up করবে

## Manual Deposit Setup

Admin Panel → 💳 Payment Methods → ➕ Add Payment Method → bKash/Nagad-এর নাম,
নম্বর, নির্দেশনা দিন।

## Order Flow

1. User Package বেছে নেয়
2. Free Fire Player ID (UID) দেয় (আগে অর্ডার করে থাকলে সেভ করা ID এক ট্যাপে reuse
   করতে পারে)
3. একটা confirmation স্ক্রিনে Package + Price + Player ID আবার দেখানো হয়, সাথে
   স্পষ্ট সতর্কতা যে ভুল ID-তে রিফান্ড সম্ভব না
4. Confirm করলে wallet থেকে atomic-ভাবে টাকা কাটা হয় (balance check + deduct +
   order creation + ledger entry — সব একসাথে, কোনো double-charge সম্ভব না)
5. Order status: 🟡 Pending Delivery, সব Admin-কে notification যায় (Player ID
   সহ)
6. Admin নিজের reseller panel/official top-up সাইট থেকে ম্যানুয়ালি top-up করে
7. Admin "✅ Mark Delivered" চাপলে ইউজার notification পায়; ঐচ্ছিকভাবে একটা
   Delivery Note ("Top-up সম্পন্ন, ২ মিনিটে দেখা যাবে") যোগ করা যায়
8. সমস্যা হলে Admin "❌ Cancel & Refund" চাপলে টাকা wallet-এ ফেরত যায়

## Testing Checklist

- [ ] `/start` — Welcome message ও মেনু দেখায়
- [ ] Package খালি থাকলে "কোনো package available নেই" দেখায়
- [ ] Package যোগ করলে সাথে সাথে ইউজারদের কাছে visible হয়
- [ ] Player ID ভুল ফরম্যাট (অক্ষর/ছোট সংখ্যা) দিলে reject হয়
- [ ] Confirmation স্ক্রিনে সঠিক Player ID দেখায়, "ID পরিবর্তন করুন" কাজ করে
- [ ] Insufficient balance-এ সঠিক এরর ও Deposit বাটন দেখায়
- [ ] সফল অর্ডারে wallet atomic-ভাবে deduct হয়, ডাবল-ট্যাপে ডাবল-চার্জ হয় না
- [ ] Admin-কে Player ID সহ notification যায়
- [ ] Deliver করলে ইউজার notification পায়, status Delivered হয়
- [ ] Cancel করলে টাকা ফেরত (refund) হয়
- [ ] Deposit approve/reject ঠিকভাবে কাজ করে, wallet ঠিকমতো credit হয়
- [ ] Ban করা ইউজার অর্ডার করতে পারে না
- [ ] Referral bonus প্রথম deposit approve হলেই যায়, দ্বিতীয়বার না

## Production Deployment (Render + Neon + cron-job.org)

এই তিনটার কম্বিনেশন VPN/SMM বটের মতোই — সংক্ষেপে:

1. **Neon.tech**-এ ফ্রি Postgres project বানান, connection string নিন, শুরুতে
   `postgresql://` কে `postgresql+asyncpg://` এবং শেষে `?sslmode=require` কে
   `?ssl=require` করে দিন
2. কোড GitHub-এ push করুন (নতুন repo)
3. Render-এ নতুন Web Service — Build: `pip install -r requirements.txt`,
   Start: `python main.py`, Instance: Free
4. Environment Variables-এ `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL` (Neon
   লিংক), `SUPPORT_USERNAME`, `PYTHON_VERSION=3.11.9` দিন
5. Deploy সফল হলে Logs-এ "Starting in WEBHOOK mode" দেখাবে
6. cron-job.org-এ প্রতি ১০ মিনিটে Render URL-এ ping করার cronjob বানান (sleep
   ঠেকাতে)

## নিরাপত্তা নোট

- Player ID plaintext-এ রাখা হয় (sensitive credential না, VPN বটের delivery
  info-র থেকে ভিন্ন)
- সব balance পরিবর্তন `services/wallet.py` দিয়ে যায় — কখনো negative হয় না,
  সবসময় `transactions` ledger-এ এন্ট্রি থাকে
- সব admin action (package/payment method যোগ/মুছা, ban/unban, balance
  adjustment, deliver/cancel order, deposit approve/reject) `activity_logs`-এ
  লেখা থাকে
