"""
SPARTAN Telegram admin bot — the ONLY admin control surface.

There is no admin panel in the app itself; everything (stars, topup
approval, settings, banners, support replies) happens here.

Raw requests-based long polling (no python-telegram-bot library),
same style as the other bots. Only responds to ADMIN_ID.

Run inside the same process as the API server (started as a background
thread from server.py) so one hosting service covers both.
"""

import time
import threading
import requests
import base64
import json

from dbhelpers import (
    db, adjust_stars, approve_topup, reject_topup, get_setting, set_setting,
    set_chat_ban, full_stats,
)

BOT_TOKEN = "8976525117:AAG9Y3QOQ_Expk5OXKJA5kp8KwWdqlwn0Ws"
ADMIN_ID = 8558032730
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# بيتفس فيه إيه الأدمن مستني يبعت بعد ما يضغط زرار معين
# ممكن تكون string ('add' / 'remove' / 'point_price' / 'cash_number' / 'banner')
# أو tuple ('reply', msisdn)
pending_action = {}


def tg_send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{API}/sendMessage", json=payload, timeout=15)
    except Exception:
        pass


def tg_send_photo(chat_id, photo_b64, caption=None, reply_markup=None):
    try:
        if "," in photo_b64:
            photo_b64 = photo_b64.split(",", 1)[1]
        photo_bytes = base64.b64decode(photo_b64)
        files = {"photo": ("screenshot.jpg", photo_bytes)}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        requests.post(f"{API}/sendPhoto", data=data, files=files, timeout=20)
    except Exception:
        pass


def tg_answer_callback(callback_id, text=""):
    try:
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text}, timeout=10)
    except Exception:
        pass


def main_menu_markup():
    return {
        "inline_keyboard": [
            [{"text": "📋 كل المستخدمين", "callback_data": "menu_all_users"}],
            [{"text": "⭐ المستخدمين اللي معاهم نقط", "callback_data": "menu_users_with_stars"}],
            [{"text": "➕ إضافة نقط", "callback_data": "menu_add_stars"},
             {"text": "➖ خصم نقط", "callback_data": "menu_remove_stars"}],
            [{"text": "📩 طلبات الشحن المعلّقة", "callback_data": "menu_pending_topups"}],
            [{"text": "💬 الرسائل", "callback_data": "menu_messages"},
             {"text": "🚫 حظر من الدعم", "callback_data": "menu_chat_ban"}],
            [{"text": "📣 إرسال إشعار", "callback_data": "menu_send_banner"}],
            [{"text": "⚙️ الإعدادات", "callback_data": "menu_settings"}],
            [{"text": "📊 الإحصائيات", "callback_data": "menu_stats"}],
        ]
    }


def send_main_menu(chat_id):
    tg_send_message(chat_id, "لوحة تحكم فكة — اختار من تحت:", main_menu_markup())


def notify_admin_new_topup(req_id, msisdn, points, amount, sender_number, screenshot_b64):
    caption = (
        f"🔔 طلب شحن جديد\n\n"
        f"الرقم: {msisdn}\n"
        f"النقاط: {points}\n"
        f"المبلغ: {amount} جنيه\n"
        f"حوّل من: {sender_number}"
    )
    markup = {
        "inline_keyboard": [[
            {"text": "✅ قبول", "callback_data": f"approve_{req_id}"},
            {"text": "❌ رفض", "callback_data": f"reject_{req_id}"},
        ]]
    }
    if screenshot_b64:
        tg_send_photo(ADMIN_ID, screenshot_b64, caption, markup)
    else:
        tg_send_message(ADMIN_ID, caption, markup)


def notify_admin_new_message(msisdn, text):
    markup = {"inline_keyboard": [[{"text": "↩️ رد", "callback_data": f"msg_reply_{msisdn}"}]]}
    tg_send_message(ADMIN_ID, f"💬 رسالة جديدة من {msisdn}:\n\n{text}", markup)


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    if chat_id != ADMIN_ID:
        return
    text = msg.get("text", "").strip()

    if text == "/start":
        pending_action.pop(chat_id, None)
        send_main_menu(chat_id)
        return

    action = pending_action.pop(chat_id, None)

    if action == "add" or action == "remove":
        parts = text.split()
        if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
            tg_send_message(chat_id, "الصيغة غلط. اكتب: الرقم مسافة عدد النقط، مثال:\n01012345678 10")
            pending_action[chat_id] = action
            return
        msisdn, points = parts[0], int(parts[1])
        delta = points if action == "add" else -points
        new_balance = adjust_stars(msisdn, delta)
        tg_send_message(chat_id, f"تم. رصيد {msisdn} دلوقتي: {new_balance} نجمة")
        send_main_menu(chat_id)
        return

    if action == "point_price":
        if not text.isdigit():
            tg_send_message(chat_id, "اكتب رقم بس، مثال: 2")
            pending_action[chat_id] = action
            return
        set_setting("point_price", text)
        tg_send_message(chat_id, f"تم تغيير سعر النقطة لـ {text} جنيه")
        send_main_menu(chat_id)
        return

    if action == "cash_number":
        set_setting("cash_number", text)
        tg_send_message(chat_id, f"تم تغيير رقم الكاش لـ {text}")
        send_main_menu(chat_id)
        return

    if action == "chat_ban":
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            tg_send_message(chat_id, "الصيغة غلط. اكتب: الرقم مسافة عدد الدقايق، مثال:\n01012345678 60\n(اكتب 0 دقيقة عشان تفك الحظر فورًا)")
            pending_action[chat_id] = action
            return
        msisdn, minutes = parts[0], int(parts[1])
        set_chat_ban(msisdn, minutes)
        if minutes == 0:
            tg_send_message(chat_id, f"تم فك حظر {msisdn} من الدعم")
        else:
            tg_send_message(chat_id, f"تم حظر {msisdn} من التواصل مع الدعم لمدة {minutes} دقيقة")
        send_main_menu(chat_id)
        return

    if action == "banner":
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            tg_send_message(chat_id, "الصيغة غلط. اكتب: all أو رقم المستخدم، مسافة، بعدين الرسالة\nمثال:\nall صيانة النهارده الساعة 5")
            pending_action[chat_id] = action
            return
        target, message = parts[0], parts[1]
        conn = db()
        conn.execute("INSERT INTO banners (message, target, created_at) VALUES (?, ?, datetime('now'))", (message, target))
        conn.commit()
        conn.close()
        tg_send_message(chat_id, "تم إرسال الإشعار")
        send_main_menu(chat_id)
        return

    if isinstance(action, tuple) and action[0] == "reply":
        msisdn = action[1]
        conn = db()
        conn.execute("INSERT INTO messages (msisdn, sender, text, created_at) VALUES (?, 'admin', ?, datetime('now'))", (msisdn, text))
        conn.commit()
        conn.close()
        tg_send_message(chat_id, f"تم إرسال الرد لـ {msisdn}")
        send_main_menu(chat_id)
        return

    send_main_menu(chat_id)


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    if chat_id != ADMIN_ID:
        tg_answer_callback(cb["id"])
        return
    data = cb["data"]
    tg_answer_callback(cb["id"])

    if data == "menu_all_users":
        conn = db()
        rows = conn.execute("SELECT msisdn, stars FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
        conn.close()
        if not rows:
            tg_send_message(chat_id, "مفيش مستخدمين لسه.")
        else:
            lines = [f"{r['msisdn']} — {r['stars']} نجمة" for r in rows]
            tg_send_message(chat_id, "👥 المستخدمين:\n\n" + "\n".join(lines))
        send_main_menu(chat_id)

    elif data == "menu_users_with_stars":
        conn = db()
        rows = conn.execute("SELECT msisdn, stars FROM users WHERE stars > 0 ORDER BY stars DESC").fetchall()
        conn.close()
        if not rows:
            tg_send_message(chat_id, "مفيش حد معاه نقط دلوقتي.")
        else:
            lines = [f"{r['msisdn']} — {r['stars']} نجمة" for r in rows]
            tg_send_message(chat_id, "⭐ عندهم نقط:\n\n" + "\n".join(lines))
        send_main_menu(chat_id)

    elif data == "menu_add_stars":
        pending_action[chat_id] = "add"
        tg_send_message(chat_id, "ابعت رقم الموبايل وعدد النقط مفصولين بمسافة، مثال:\n01012345678 10")

    elif data == "menu_remove_stars":
        pending_action[chat_id] = "remove"
        tg_send_message(chat_id, "ابعت رقم الموبايل وعدد النقط اللي هتخصمها مفصولين بمسافة، مثال:\n01012345678 5")

    elif data == "menu_pending_topups":
        conn = db()
        rows = conn.execute("SELECT * FROM topup_requests WHERE status='pending' ORDER BY created_at DESC").fetchall()
        conn.close()
        if not rows:
            tg_send_message(chat_id, "مفيش طلبات شحن معلّقة.")
        else:
            for r in rows:
                notify_admin_new_topup(r["id"], r["msisdn"], r["points"], r["amount"], r["sender_number"], r["screenshot_base64"])
        send_main_menu(chat_id)

    elif data == "menu_messages":
        conn = db()
        rows = conn.execute(
            "SELECT msisdn, MAX(created_at) last_at, COUNT(*) c FROM messages GROUP BY msisdn ORDER BY last_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        if not rows:
            tg_send_message(chat_id, "مفيش محادثات لسه.")
            send_main_menu(chat_id)
        else:
            buttons = [[{"text": f"{r['msisdn']} ({r['c']})", "callback_data": f"conv_{r['msisdn']}"}] for r in rows]
            tg_send_message(chat_id, "💬 المحادثات:", {"inline_keyboard": buttons})

    elif data.startswith("conv_"):
        msisdn = data.split("_", 1)[1]
        conn = db()
        rows = conn.execute("SELECT sender, text, created_at FROM messages WHERE msisdn=? ORDER BY created_at ASC", (msisdn,)).fetchall()
        conn.close()
        lines = [f"{'المستخدم' if r['sender']=='user' else 'أنت'}: {r['text']}" for r in rows]
        markup = {"inline_keyboard": [[{"text": "↩️ رد", "callback_data": f"msg_reply_{msisdn}"}]]}
        tg_send_message(chat_id, f"محادثة {msisdn}:\n\n" + "\n".join(lines[-20:]), markup)

    elif data.startswith("msg_reply_"):
        msisdn = data.split("msg_reply_", 1)[1]
        pending_action[chat_id] = ("reply", msisdn)
        tg_send_message(chat_id, f"اكتب الرد اللي هيتبعت لـ {msisdn}:")

    elif data == "menu_send_banner":
        pending_action[chat_id] = "banner"
        tg_send_message(chat_id, "اكتب: all أو رقم المستخدم، مسافة، بعدين الرسالة\nمثال:\nall صيانة النهارده الساعة 5")

    elif data == "menu_chat_ban":
        pending_action[chat_id] = "chat_ban"
        tg_send_message(chat_id, "اكتب: رقم الموبايل مسافة عدد الدقايق، مثال:\n01012345678 60\n(اكتب 0 دقيقة عشان تفك الحظر فورًا)")

    elif data == "menu_settings":
        pp = get_setting("point_price")
        cn = get_setting("cash_number")
        re_ = get_setting("requests_enabled")
        markup = {
            "inline_keyboard": [
                [{"text": "💰 تغيير سعر النقطة", "callback_data": "set_point_price"}],
                [{"text": "🏦 تغيير رقم الكاش", "callback_data": "set_cash_number"}],
                [{"text": ("⏸ إيقاف" if re_ == "1" else "▶️ تشغيل") + " طلبات الشحن", "callback_data": "toggle_requests"}],
            ]
        }
        tg_send_message(chat_id, f"⚙️ الإعدادات الحالية:\n\nسعر النقطة: {pp} جنيه\nرقم الكاش: {cn}\nطلبات الشحن: {'مفعّلة' if re_=='1' else 'متوقفة'}", markup)

    elif data == "set_point_price":
        pending_action[chat_id] = "point_price"
        tg_send_message(chat_id, "اكتب سعر النقطة الجديد (رقم بس)، مثال: 2")

    elif data == "set_cash_number":
        pending_action[chat_id] = "cash_number"
        tg_send_message(chat_id, "اكتب رقم الكاش الجديد")

    elif data == "toggle_requests":
        cur = get_setting("requests_enabled")
        set_setting("requests_enabled", "0" if cur == "1" else "1")
        tg_send_message(chat_id, "تم التغيير")
        send_main_menu(chat_id)

    elif data == "menu_stats":
        s = full_stats()
        tg_send_message(chat_id, (
            "📊 الإحصائيات الكاملة:\n\n"
            f"👥 إجمالي المستخدمين: {s['users_count']}\n"
            f"⭐ إجمالي النقاط في التطبيق: {s['total_stars']}\n\n"
            f"✅ عمليات شحن كروت ناجحة: {s['successful_charges']}\n"
            f"✅ عمليات شحن رصيد ناجحة: {s['successful_recharges']}\n"
            f"📆 عمليات اليوم: {s['charges_today']} | عمليات الشهر: {s['charges_month']}\n\n"
            f"📩 طلبات شحن معلّقة: {s['pending_topups']}\n"
            f"✔️ طلبات مقبولة: {s['approved_topups']} | ✖️ طلبات مرفوضة: {s['rejected_topups']}\n\n"
            f"💬 إجمالي الرسائل: {s['total_messages']}\n"
            f"🚫 محظورين من الشحن: {s['banned_users']} | 🔇 محظورين من الدعم دلوقتي: {s['chat_banned']}"
        ))
        send_main_menu(chat_id)

    elif data.startswith("approve_"):
        req_id = int(data.split("_")[1])
        row = approve_topup(req_id)
        if row:
            tg_send_message(chat_id, f"✅ تم قبول الطلب وإضافة {row['points']} نجمة لـ {row['msisdn']}")
        else:
            tg_send_message(chat_id, "الطلب اتعالج قبل كده أو مش موجود.")

    elif data.startswith("reject_"):
        req_id = int(data.split("_")[1])
        row = reject_topup(req_id)
        if row:
            tg_send_message(chat_id, f"❌ تم رفض الطلب بتاع {row['msisdn']}")
        else:
            tg_send_message(chat_id, "الطلب اتعالج قبل كده أو مش موجود.")


def poll_loop():
    offset = 0
    while True:
        try:
            resp = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=40)
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
        except Exception:
            time.sleep(3)


def start_bot_thread():
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()
