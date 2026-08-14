"""
SPARTAN backend skeleton (FastAPI).

Each user purchases from their own Vodafone line — that logic now runs
natively ON THE DEVICE (see android-plugin/VodafonePurchasePlugin.kt),
NOT through this server. This backend is only for things that must be
shared/central: the admin panel (cash-out numbers, permitted star-transfer
users) and basic user records (name + stars balance).

This file is a skeleton: routing and data model only. It is NOT wired to
a database yet — cash numbers and permitted users are in-memory lists as
placeholders.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="SPARTAN backend")

# ---------------- in-memory placeholders (replace with a real DB) ----------------
CASH_NUMBERS = ["01012345678", "01098765432"]
PERMITTED_STAR_TRANSFER_USERS = ["01025411874"]
USERS = {}  # msisdn -> {"name": ..., "stars": 0, "device_id": ...}
ADMIN_CREDENTIALS = {"username": "admin", "password": "CHANGE_ME"}

CARD_DETAILS = {
    "Fakka_2.5_Unite": "20 وحدة + 1 واتساب - صالح 45 يوم",
    "Fakka_4.25_Unite": "190 وحدة - حتى منتصف الليل",
    "Fakka_5_Unite": "80 وحدة/ميجا - يومين",
    "Fakka_6_NewUnite": "225 وحدة - صالح لـ 1 يوم",
    "Fakka_7_Unite": "300 وحدة - صالح لـ 3 أيام",
    "Fakka_9_Unite": "400 وحدة + 50 واتساب - 4 أيام",
    "Fakka_10_Unite": "300 دقيقة لكل الشبكات أو ميجا - يومين",
    "Fakka_10_NewUnite": "450 وحدة - صالح لـ 7 أيام",
    "Fakka_10.5_Unite": "400 وحدة - صالح لـ 7 أيام",
    "Fakka_11.5_Unite": "450 وحدة/ميجا - 7 أيام",
    "Fakka_12_Unite": "450 وحدة - صالح لـ 7 أيام",
    "Fakka_12.5_Unite": "425 وحدة - صالح لـ 6 أيام",
    "Fakka_13_Unite": "300 وحدة (650 من الكاش) - صالح ليومين",
    "Fakka_13.5_Unite": "625 وحدة/ميجا - 7 أيام",
    "Fakka_15_Unite": "625 وحدة - صالح لـ 7 أيام",
    "Fakka_15_NewUnite": "625 وحدة - صالح لـ 7 أيام",
    "Fakka_15.5_Unite": "625 وحدة - صالح لـ 7 أيام",
    "Fakka_16.5_Unite": "425 وحدة - صالح لـ 6 أيام",
    "Fakka_17.5_Unite": "650 وحدة/ميجا - 10 أيام",
    "Fakka_19.5_NewUnite": "550 وحدة (975 من الكاش) - صالح لـ 7 أيام",
    "Fakka_20_Unite": "750 وحدة/ميجا - 10 أيام",
    "Fakka_26_Unite": "750 وحدة (1300 من الكاش) - صالح لـ 10 أيام",
    "Mared_10_Minuts": "450 دقيقة لكل الشبكات - صالح لـ 7 أيام",
    "Mared_10_Flexs": "450 فليكس - صالح لـ 7 أيام",
    "Mared_10_Social": "450 ميجا سوشيال - صالح لـ 7 أيام",
}


# ---------------- API models ----------------
class RegisterBody(BaseModel):
    device_id: str
    full_name: str
    msisdn: str


class AdminLoginBody(BaseModel):
    username: str
    password: str


class CashNumberBody(BaseModel):
    number: str


class PermittedUserBody(BaseModel):
    msisdn: str


# ---------------- user-facing endpoints ----------------
@app.post("/register")
def register(body: RegisterBody):
    USERS[body.msisdn] = {"name": body.full_name, "stars": 0, "device_id": body.device_id}
    return {"ok": True}


@app.get("/cards")
def list_cards():
    return CARD_DETAILS


# ---------------- admin endpoints ----------------
@app.post("/admin/login")
def admin_login(body: AdminLoginBody):
    if body.username == ADMIN_CREDENTIALS["username"] and body.password == ADMIN_CREDENTIALS["password"]:
        return {"ok": True}
    raise HTTPException(401, "بيانات دخول غلط")


@app.get("/admin/cash-numbers")
def get_cash_numbers():
    return CASH_NUMBERS


@app.post("/admin/cash-numbers")
def add_cash_number(body: CashNumberBody):
    CASH_NUMBERS.append(body.number)
    return CASH_NUMBERS


@app.delete("/admin/cash-numbers/{number}")
def delete_cash_number(number: str):
    if number in CASH_NUMBERS:
        CASH_NUMBERS.remove(number)
    return CASH_NUMBERS


@app.get("/admin/permitted-users")
def get_permitted_users():
    return PERMITTED_STAR_TRANSFER_USERS


@app.post("/admin/permitted-users")
def add_permitted_user(body: PermittedUserBody):
    PERMITTED_STAR_TRANSFER_USERS.append(body.msisdn)
    return PERMITTED_STAR_TRANSFER_USERS


@app.delete("/admin/permitted-users/{msisdn}")
def delete_permitted_user(msisdn: str):
    if msisdn in PERMITTED_STAR_TRANSFER_USERS:
        PERMITTED_STAR_TRANSFER_USERS.remove(msisdn)
    return PERMITTED_STAR_TRANSFER_USERS
