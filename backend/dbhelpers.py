"""
Shared DB helpers for SPARTAN backend — used by both server.py (the API
that the app talks to) and telegram_bot.py (the admin control bot).
Keeping this in one place means both always agree on the same data.
"""

import sqlite3
import datetime

DB_PATH = "spartan.db"

CARD_DETAILS = {
    "Fakka_2.5_Unite": "45 وحدة + 20 ميجا واتساب - صالح ليوم واحد",
    "Fakka_4.25_Unite": "190 وحدة/ميجا - صالح ليوم واحد",
    "Fakka_6_NewUnite": "225 وحدة/ميجا - صالح ليوم واحد",
    "Fakka_9_Unite": "400 وحدة + 50 ميجا واتساب - صالح لـ 4 أيام",
    "Fakka_11.5_Unite": "450 وحدة/ميجا - صالح لـ 7 أيام",
    "Fakka_13.5_Unite": "625 وحدة/ميجا - صالح لـ 7 أيام",
    "Fakka_17.5_Unite": "650 وحدة/ميجا - صالح لـ 10 أيام",
    "Fakka_20_Unite": "750 وحدة/ميجا - صالح لـ 10 أيام",
}


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
    c.execute("""CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, msisdn TEXT, message TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS topup_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, msisdn TEXT, points INTEGER, amount INTEGER,
        sender_number TEXT, screenshot_base64 TEXT, status TEXT DEFAULT 'pending', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS banners (
        id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, target TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, msisdn TEXT, sender TEXT, text TEXT, created_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

    defaults = {"point_price": "2", "cash_number": "01556058014", "requests_enabled": "1"}
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


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


def log_activity(msisdn, message):
    conn = db()
    conn.execute("INSERT INTO activity_log (msisdn, message, created_at) VALUES (?, ?, ?)", (msisdn, message, now()))
    conn.commit()
    conn.close()


def ensure_user(msisdn):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    if not row:
        conn.execute("INSERT INTO users (msisdn, name, stars, created_at) VALUES (?, ?, 0, ?)", (msisdn, "", now()))
        conn.commit()
    conn.close()


def adjust_stars(msisdn, delta):
    ensure_user(msisdn)
    conn = db()
    conn.execute("UPDATE users SET stars = stars + ? WHERE msisdn=?", (delta, msisdn))
    conn.commit()
    row = conn.execute("SELECT stars FROM users WHERE msisdn=?", (msisdn,)).fetchone()
    conn.close()
    word = "إضافة" if delta >= 0 else "خصم"
    log_activity(msisdn, f"تم {word} {abs(delta)} نجمة بواسطة الإدارة")
    return row["stars"]


def approve_topup(req_id):
    conn = db()
    reqrow = conn.execute("SELECT * FROM topup_requests WHERE id=?", (req_id,)).fetchone()
    if not reqrow or reqrow["status"] != "pending":
        conn.close()
        return None
    conn.execute("UPDATE topup_requests SET status='approved' WHERE id=?", (req_id,))
    conn.execute("UPDATE users SET stars = stars + ?, consecutive_rejections = 0 WHERE msisdn=?", (reqrow["points"], reqrow["msisdn"]))
    conn.execute(
        "INSERT INTO banners (message, target, created_at) VALUES (?, ?, ?)",
        (f"تم قبول طلبك وإضافة {reqrow['points']} نجمة", reqrow["msisdn"], now()),
    )
    conn.commit()
    conn.close()
    log_activity(reqrow["msisdn"], f"تم إضافة {reqrow['points']} نجمة (طلب شحن مقبول)")
    return reqrow


def reject_topup(req_id):
    conn = db()
    reqrow = conn.execute("SELECT * FROM topup_requests WHERE id=?", (req_id,)).fetchone()
    if not reqrow or reqrow["status"] != "pending":
        conn.close()
        return None
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
    log_activity(reqrow["msisdn"], "تم رفض طلب شحن النقاط")
    return reqrow
