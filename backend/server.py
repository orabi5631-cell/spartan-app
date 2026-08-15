"""
SPARTAN backend (FastAPI + SQLite).

- Card purchases run on-device (see android-plugin/VodafonePurchasePlugin.java).
- This server stores everything that must be shared/persistent: per-user
  transaction logs, star balances, top-up requests, banners, and admin settings.
- Uses SQLite (a local file, spartan.db) — no external database needed.
"""

import sqlite3
import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="SPARTAN backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "spartan.db"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        msisdn TEXT PRIMARY KEY, name TEXT, stars INTEGER DEFAULT 0,
        device_id TEXT, banned INTEGER DEFAULT 0, consecutive_rejections INTEGER DEFAULT 0,
        created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, msisdn TEXT, card_id TEXT,
        receiver TEXT, status TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS topup_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, msisdn TEXT, points INTEGER, amount INTEGER,
        sender_number TEXT, status TEXT DEFAULT 'pending', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS banners (
        id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, target TEXT, created_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    defaults = {"point_price": "2", "cash_number": "01556058014", "requests_enabled": "1",
                "admin_username": "admin", "admin_password": "CHANGE_ME"}
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


init_db()


def now():
    return datetime.datetime.utcnow().isoformat()


def get_setting(key):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=?",
        (key, value, value),
    )
    conn.commit()
    conn.close()


CARD_DETAILS = {
    "Fakka_6_NewUnite": "225 وحدة/ميجا - صالح لـ 4 أيام",
    "Fakka_9_Unite": "400 وحدة + 50 ميجا واتساب - صالح لـ 4 أيام",
    "Fakka_11.5_Unite": "450 وحدة/ميجا - صالح لـ 7 أيام",
    "Fakka_13.5_Unite": "625 وحدة/ميجا - صالح لـ 7 أيام",
    "Fakka_17.5_Unite": "650 وحدة/ميجا - صالح لـ 10 أيام",
    "Fakka_20_Unite": "750 وحدة/ميجا - صالح لـ 10 أيام",
}


# ---------------- models ----------------
class RegisterBody(BaseModel):
    device_id: str
    full_name: str
    msisdn: str


class TransactionBody(BaseModel):
    msisdn: str
    card_id: str
    receiver: str
    status: str


class TopupRequestBody(BaseModel):
    msisdn: str
    points: int
    amount: int
    sender_number: str


class AdminLoginBody(BaseModel):
    username: str
    password: str


class SettingsBody(BaseModel):
    point_price: Optional[int] = None
    cash_number: Optional[str] = None
    requests_enabled: Optional[bool] = None


class StarsAdjustBody(BaseModel):
    delta: int


class BannerBody(BaseModel):
    message: str
    target: str = "all"  # "all" or a specific msisdn


def ensure_user(msisdn):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    if not row:
        conn.execute("INSERT INTO users (msisdn, name, stars, created_at) VALUES (?, ?, 0, ?)", (msisdn, "", now()))
        conn.commit()
    conn.close()


# ---------------- user-facing ----------------
@app.post("/register")
def register(body: RegisterBody):
    conn = db()
    conn.execute(
        "INSERT INTO users (msisdn, name, device_id, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(msisdn) DO UPDATE SET name=?, device_id=?",
        (body.msisdn, body.full_name, body.device_id, now(), body.full_name, body.device_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/cards")
def list_cards():
    return CARD_DETAILS


@app.post("/transactions")
def add_transaction(body: TransactionBody):
    ensure_user(body.msisdn)
    conn = db()
    conn.execute(
        "INSERT INTO transactions (msisdn, card_id, receiver, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (body.msisdn, body.card_id, body.receiver, body.status, now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/transactions/{msisdn}")
def get_transactions(msisdn: str):
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    conn = db()
    conn.execute("DELETE FROM transactions WHERE msisdn=? AND created_at < ?", (msisdn, cutoff))
    conn.commit()
    rows = conn.execute(
        "SELECT card_id, receiver, status, created_at FROM transactions WHERE msisdn=? ORDER BY created_at DESC",
        (msisdn,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/topup-requests")
def create_topup_request(body: TopupRequestBody):
    ensure_user(body.msisdn)
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE msisdn=?", (body.msisdn,)).fetchone()
    if user["banned"]:
        conn.close()
        raise HTTPException(403, "محظور من طلبات الشحن بسبب رفض متكرر")
    if get_setting("requests_enabled") != "1":
        conn.close()
        raise HTTPException(403, "طلبات الشحن متوقفة مؤقتًا")
    pending = conn.execute(
        "SELECT * FROM topup_requests WHERE msisdn=? AND status='pending'", (body.msisdn,)
    ).fetchone()
    if pending:
        conn.close()
        raise HTTPException(409, "عندك طلب قيد المراجعة بالفعل")
    conn.execute(
        "INSERT INTO topup_requests (msisdn, points, amount, sender_number, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
        (body.msisdn, body.points, body.amount, body.sender_number, now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/topup-requests/{msisdn}")
def get_user_topup_requests(msisdn: str):
    conn = db()
    rows = conn.execute(
        "SELECT id, points, amount, sender_number, status, created_at FROM topup_requests WHERE msisdn=? ORDER BY created_at DESC",
        (msisdn,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/banners/{msisdn}")
def get_banners(msisdn: str):
    conn = db()
    rows = conn.execute(
        "SELECT id, message, created_at FROM banners WHERE target=? OR target='all' ORDER BY created_at DESC LIMIT 20",
        (msisdn,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/public-settings")
def public_settings():
    return {
        "point_price": int(get_setting("point_price")),
        "cash_number": get_setting("cash_number"),
        "requests_enabled": get_setting("requests_enabled") == "1",
    }


# ---------------- admin ----------------
@app.post("/admin/login")
def admin_login(body: AdminLoginBody):
    if body.username == get_setting("admin_username") and body.password == get_setting("admin_password"):
        return {"ok": True}
    raise HTTPException(401, "بيانات دخول غلط")


@app.get("/admin/stats")
def admin_stats():
    conn = db()
    users_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.datetime.utcnow().strftime("%Y-%m")
    cards_today = conn.execute("SELECT COUNT(*) c FROM transactions WHERE created_at LIKE ?", (today + "%",)).fetchone()["c"]
    cards_month = conn.execute("SELECT COUNT(*) c FROM transactions WHERE created_at LIKE ?", (month + "%",)).fetchone()["c"]
    total_stars = conn.execute("SELECT COALESCE(SUM(stars),0) s FROM users").fetchone()["s"]
    conn.close()
    return {"users_count": users_count, "cards_today": cards_today, "cards_month": cards_month, "total_stars": total_stars}


@app.get("/admin/users")
def admin_list_users():
    conn = db()
    rows = conn.execute("SELECT msisdn, name, stars, device_id, banned, created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/admin/users/{msisdn}/stars")
def admin_adjust_stars(msisdn: str, body: StarsAdjustBody):
    ensure_user(msisdn)
    conn = db()
    conn.execute("UPDATE users SET stars = stars + ? WHERE msisdn=?", (body.delta, msisdn))
    conn.commit()
    row = conn.execute("SELECT stars FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    conn.close()
    return {"stars": row["stars"]}


@app.get("/admin/topup-requests")
def admin_list_topup_requests():
    conn = db()
    rows = conn.execute("SELECT * FROM topup_requests ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/admin/topup-requests/{req_id}/approve")
def admin_approve_topup(req_id: int):
    conn = db()
    reqrow = conn.execute("SELECT * FROM topup_requests WHERE id=?", (req_id,)).fetchone()
    if not reqrow:
        conn.close()
        raise HTTPException(404, "الطلب مش موجود")
    conn.execute("UPDATE topup_requests SET status='approved' WHERE id=?", (req_id,))
    conn.execute("UPDATE users SET stars = stars + ?, consecutive_rejections = 0 WHERE msisdn=?", (reqrow["points"], reqrow["msisdn"]))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/admin/topup-requests/{req_id}/reject")
def admin_reject_topup(req_id: int):
    conn = db()
    reqrow = conn.execute("SELECT * FROM topup_requests WHERE id=?", (req_id,)).fetchone()
    if not reqrow:
        conn.close()
        raise HTTPException(404, "الطلب مش موجود")
    conn.execute("UPDATE topup_requests SET status='rejected' WHERE id=?", (req_id,))
    conn.execute("UPDATE users SET consecutive_rejections = consecutive_rejections + 1 WHERE msisdn=?", (reqrow["msisdn"],))
    user = conn.execute("SELECT consecutive_rejections FROM users WHERE msisdn=?", (reqrow["msisdn"],)).fetchone()
    if user["consecutive_rejections"] >= 2:
        conn.execute("UPDATE users SET banned=1 WHERE msisdn=?", (reqrow["msisdn"],))
    conn.execute(
        "INSERT INTO banners (message, target, created_at) VALUES (?, ?, ?)",
        ("تم رفض طلب شحن النقاط بتاعك", reqrow["msisdn"], now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/admin/banners")
def admin_send_banner(body: BannerBody):
    conn = db()
    conn.execute("INSERT INTO banners (message, target, created_at) VALUES (?, ?, ?)", (body.message, body.target, now()))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/admin/settings")
def admin_update_settings(body: SettingsBody):
    if body.point_price is not None:
        set_setting("point_price", str(body.point_price))
    if body.cash_number is not None:
        set_setting("cash_number", body.cash_number)
    if body.requests_enabled is not None:
        set_setting("requests_enabled", "1" if body.requests_enabled else "0")
    return {"ok": True}


@app.get("/admin/settings")
def admin_get_settings():
    return public_settings()
