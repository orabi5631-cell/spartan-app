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
        chat_banned_until TEXT, created_at TEXT)""")
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

    # ترقية آمنة لقاعدة بيانات موجودة بالفعل على الاستضافة (من غير ما نمسحها)
    try:
        c.execute("ALTER TABLE users ADD COLUMN chat_banned_until TEXT")
    except sqlite3.OperationalError:
        pass

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


def set_chat_ban(msisdn, minutes):
    ensure_user(msisdn)
    conn = db()
    if minutes <= 0:
        conn.execute("UPDATE users SET chat_banned_until=NULL WHERE msisdn=?", (msisdn,))
    else:
        until = (datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)).isoformat()
        conn.execute("UPDATE users SET chat_banned_until=? WHERE msisdn=?", (until, msisdn))
    conn.commit()
    conn.close()


def full_stats():
    conn = db()
    users_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    total_stars = conn.execute("SELECT COALESCE(SUM(stars),0) s FROM users").fetchone()["s"]
    pending_topups = conn.execute("SELECT COUNT(*) c FROM topup_requests WHERE status='pending'").fetchone()["c"]
    approved_topups = conn.execute("SELECT COUNT(*) c FROM topup_requests WHERE status='approved'").fetchone()["c"]
    rejected_topups = conn.execute("SELECT COUNT(*) c FROM topup_requests WHERE status='rejected'").fetchone()["c"]
    successful_charges = conn.execute("SELECT COUNT(*) c FROM activity_log WHERE message LIKE 'تم شحن كارت%'").fetchone()["c"]
    successful_recharges = conn.execute("SELECT COUNT(*) c FROM activity_log WHERE message LIKE 'تم شحن رصيد%'").fetchone()["c"]
    banned_users = conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
    chat_banned = conn.execute("SELECT COUNT(*) c FROM users WHERE chat_banned_until IS NOT NULL AND chat_banned_until > ?", (now(),)).fetchone()["c"]
    total_messages = conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.datetime.utcnow().strftime("%Y-%m")
    charges_today = conn.execute("SELECT COUNT(*) c FROM activity_log WHERE message LIKE 'تم شحن%' AND created_at LIKE ?", (today + "%",)).fetchone()["c"]
    charges_month = conn.execute("SELECT COUNT(*) c FROM activity_log WHERE message LIKE 'تم شحن%' AND created_at LIKE ?", (month + "%",)).fetchone()["c"]
    conn.close()
    return {
        "users_count": users_count, "total_stars": total_stars,
        "pending_topups": pending_topups, "approved_topups": approved_topups, "rejected_topups": rejected_topups,
        "successful_charges": successful_charges, "successful_recharges": successful_recharges,
        "banned_users": banned_users, "chat_banned": chat_banned, "total_messages": total_messages,
        "charges_today": charges_today, "charges_month": charges_month,
    }
