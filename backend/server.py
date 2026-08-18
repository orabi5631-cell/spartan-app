"""
SPARTAN backend (FastAPI + SQLite) + Telegram admin bot in one process.

The app talks to this server for user-facing data only (balance, cards,
activity log, top-up requests, support messages, banners). There is NO
web admin API — all admin control (stars, approvals, settings, banners,
support replies) happens through the Telegram bot (telegram_bot.py),
which runs as a background thread inside this same process.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from dbhelpers import db, init_db, now, get_setting, log_activity, ensure_user, CARD_DETAILS
import telegram_bot

app = FastAPI(title="SPARTAN backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


@app.on_event("startup")
def _start_bot():
    telegram_bot.start_bot_thread()


class RegisterBody(BaseModel):
    device_id: str
    full_name: str
    msisdn: str


class ActivityBody(BaseModel):
    msisdn: str
    message: str


class TopupRequestBody(BaseModel):
    msisdn: str
    points: int
    amount: int
    sender_number: str
    screenshot_base64: Optional[str] = None


class MessageBody(BaseModel):
    msisdn: str
    sender: str
    text: str


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


@app.get("/balance/{msisdn}")
def get_balance(msisdn: str):
    ensure_user(msisdn)
    conn = db()
    row = conn.execute("SELECT stars FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    conn.close()
    return {"stars": row["stars"]}


@app.post("/deduct-point/{msisdn}")
def deduct_point(msisdn: str):
    ensure_user(msisdn)
    conn = db()
    row = conn.execute("SELECT stars FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    if row["stars"] < 1:
        conn.close()
        raise HTTPException(402, "رصيد النقاط مش كافي")
    conn.execute("UPDATE users SET stars = stars - 1 WHERE msisdn=?", (msisdn,))
    conn.commit()
    newrow = conn.execute("SELECT stars FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    conn.close()
    return {"ok": True, "stars": newrow["stars"]}


@app.post("/activity")
def add_activity(body: ActivityBody):
    ensure_user(body.msisdn)
    log_activity(body.msisdn, body.message)
    return {"ok": True}


@app.get("/activity/{msisdn}")
def get_activity(msisdn: str):
    conn = db()
    rows = conn.execute(
        "SELECT message, created_at FROM activity_log WHERE msisdn=? ORDER BY created_at DESC", (msisdn,)
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
    cur = conn.execute(
        "INSERT INTO topup_requests (msisdn, points, amount, sender_number, screenshot_base64, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (body.msisdn, body.points, body.amount, body.sender_number, body.screenshot_base64, now()),
    )
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    log_activity(body.msisdn, f"طلب شحن {body.points} نجمة — قيد المراجعة")
    telegram_bot.notify_admin_new_topup(req_id, body.msisdn, body.points, body.amount, body.sender_number, body.screenshot_base64)
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


@app.post("/messages")
def send_message(body: MessageBody):
    ensure_user(body.msisdn)
    conn = db()
    conn.execute(
        "INSERT INTO messages (msisdn, sender, text, created_at) VALUES (?, ?, ?, ?)",
        (body.msisdn, body.sender, body.text, now()),
    )
    conn.commit()
    conn.close()
    if body.sender == "user":
        telegram_bot.notify_admin_new_message(body.msisdn, body.text)
    return {"ok": True}


@app.get("/messages/{msisdn}")
def get_messages(msisdn: str):
    conn = db()
    rows = conn.execute(
        "SELECT sender, text, created_at FROM messages WHERE msisdn=? ORDER BY created_at ASC", (msisdn,)
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
