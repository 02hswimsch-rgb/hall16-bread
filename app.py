"""Hall 16 Bread — bakery bread pre-order web app (Hall 16, NTU).

Customers pick how many breads they want, pay via PayLah! and collect at
Pantry C, Level 3 (10:00–11:30 PM, Sun–Wed nights, while stock lasts).

Customers pay by PayLah! first and upload a screenshot of the payment.
The boss page (open with  ?boss  at the end of the URL) lets the owner:
  • open / close the shop
  • change the price and the stock quantity
  • see each payment screenshot, then delete it
  • press "Payment collected" on an order -> stock drops
  • tick people off the "To collect" list (tap their @handle to open Telegram)

Shop settings + orders are saved in shop_data.json next to this file.
Secrets (st.secrets): BOSS_PASSWORD (required for boss page),
BOT_TOKEN + OWNER_CHAT_ID (optional, Telegram alert on new orders).
"""

import base64
import json
import os
import re
import threading
from datetime import datetime

import pytz
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SHOP_NAME = "Hall 16 Bread"
PAYLAH_NUMBER = "8822 6946"
DEFAULT_PRICE = 1.10
DEFAULT_STOCK = 20
MEETUP_POINT = "Pantry C, Level 3 (Hall 16)"
MEETUP_TIME = "10:00 PM – 11:30 PM"
MEETUP_DAYS = "Sunday – Wednesday nights"
MAX_PER_ORDER = 10

SGT = pytz.timezone("Asia/Singapore")
HERO_IMAGE = "bread.png"      # add a bread photo with this name (optional)
PROOF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payment_proofs")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop_data.json")

st.set_page_config(page_title=SHOP_NAME, page_icon="🍞", layout="centered")


# ---------------------------------------------------------------------------
# Shop data (price, stock, open/closed, orders) — shared by all visitors
# ---------------------------------------------------------------------------
@st.cache_resource
def _lock():
    return threading.Lock()


def _default_data():
    return {"price": DEFAULT_PRICE, "stock": DEFAULT_STOCK, "is_open": False,
            "next_id": 1, "orders": []}


def load_data():
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        base = _default_data()
        base.update(data)
        return base
    except Exception:
        return _default_data()


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


def update_data(fn):
    """Load, change with fn(data), save — all under one lock. Returns fn's result."""
    with _lock():
        data = load_data()
        result = fn(data)
        save_data(data)
        return result


def reserved_qty(data):
    """Breads held by orders that are waiting for payment."""
    return sum(o["qty"] for o in data["orders"] if o["status"] == "pending")


def available_qty(data):
    return max(0, int(data["stock"]) - reserved_qty(data))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return None


def img_to_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None


def now_sgt():
    return datetime.now(SGT)


def money(x):
    return f"${x:.2f}"


def confirm_text(o):
    return (
        f"Hi {o['name']}! ✅ Payment received for order #{o['id']} — "
        f"{o['qty']} x bread ({money(o['total'])}).\n"
        f"Collect at {MEETUP_POINT}, {MEETUP_TIME} tonight.\n"
        f"Thank you! — {SHOP_NAME} 🍞"
    )


def clean_handle(text):
    """'@ John_Tan ' / 't.me/john_tan' -> '@John_Tan'. Returns '' if invalid."""
    h = text.strip().replace("https://", "").replace("t.me/", "").lstrip("@").strip()
    return "@" + h if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", h) else ""


def tg_link(handle):
    return f"https://t.me/{handle.lstrip('@')}"


def save_proof(order_id, upload):
    os.makedirs(PROOF_DIR, exist_ok=True)
    ext = os.path.splitext(upload.name)[1].lower() or ".jpg"
    fname = f"{order_id}{ext}"
    with open(os.path.join(PROOF_DIR, fname), "wb") as f:
        f.write(upload.getvalue())
    return fname


def delete_proof(fname):
    if fname:
        try:
            os.remove(os.path.join(PROOF_DIR, fname))
        except Exception:
            pass


def send_telegram(chat_id, text):
    token = get_secret("BOT_TOKEN")
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        return requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10).ok
    except Exception:
        return False


def notify_owner(o):
    owner_id = get_secret("OWNER_CHAT_ID")
    if not owner_id:
        return
    send_telegram(owner_id, "\n".join([
        f"🆕 NEW ORDER #{o['id']} — {SHOP_NAME}",
        f"🍞 {o['qty']} x bread @ {money(o['price'])}",
        f"💰 TOTAL: {money(o['total'])}",
        f"👤 {o['name']}  📱 {o['contact']}",
        f"📝 {o['special'] or 'No notes'}",
        "Check PayLah!, then press 'Payment collected' on the boss page.",
    ]))


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
def inject_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&display=swap');
        .stApp { background-color: #FDF6EC; }
        .block-container { max-width: 480px; padding-top: 1.2rem; padding-bottom: 2.5rem; }
        [data-testid="stHeader"] { background: transparent; }
        #MainMenu, footer { visibility: hidden; }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #FFF8F0; border: 1px solid #ECD9C0;
            border-radius: 16px; box-shadow: 0 1px 4px rgba(139,69,19,0.06);
        }
        .kt-title { text-align:center; font-family:'Playfair Display',Georgia,serif;
            color:#8B4513; font-size:2.3rem; font-weight:900; margin:0.2rem 0 0; line-height:1.15; }
        .kt-tagline { text-align:center; font-style:italic; color:#8B4513; opacity:0.85;
            font-size:1rem; margin:0.1rem 0 0.7rem; }
        .kt-hero { width:100%; border-radius:16px; display:block; margin-bottom:8px;
            max-height:240px; object-fit:cover; }
        .kt-hero-placeholder { width:100%; min-height:150px; border-radius:16px;
            background:#C68B4E; color:#FFF8F0; display:flex; align-items:center;
            justify-content:center; font-family:'Playfair Display',Georgia,serif;
            font-size:1.6rem; font-weight:700; text-align:center; margin-bottom:8px; padding:20px; }
        .kt-price { text-align:center; margin:4px 0 8px; color:#3B2407; }
        .kt-price b { font-size:2.2rem; color:#B91C1C; font-weight:900; }
        .kt-info { background:#FFF3CD; border:1px solid #F5A623; border-radius:14px;
            padding:12px 16px; margin-bottom:8px; color:#3B2407; font-size:0.95rem; line-height:1.6; }
        .kt-banner-closed { background:#FDECEA; border:1px solid #E0B4B4; color:#B91C1C;
            border-radius:14px; padding:14px 16px; text-align:center; font-weight:700; margin-bottom:8px; }
        .kt-banner-open { background:#E7F6EC; border:1px solid #A7D7B7; color:#1B7A3D;
            border-radius:14px; padding:14px 16px; text-align:center; font-weight:700; margin-bottom:8px; }
        .kt-section-label { font-weight:800; color:#8B4513; font-size:1.05rem; margin:2px 0; }
        .kt-total { background:#FFF3CD; border:1px solid #F5A623; border-radius:14px;
            padding:16px 18px; margin:10px 0 6px; color:#3B2407; }
        .kt-total-row { display:flex; justify-content:space-between; gap:12px; font-size:0.95rem; margin:4px 0; }
        .kt-total-final { display:flex; justify-content:space-between; font-size:1.55rem;
            font-weight:900; margin-top:8px; color:#8B4513; }
        .kt-summary { background:#FFF8F0; border:1px solid #ECD9C0; border-radius:16px;
            padding:16px 18px; margin:8px 0; }
        .kt-summary-title { font-weight:800; color:#8B4513; font-size:1.15rem; margin-bottom:10px; }
        .kt-qr { display:block; margin:12px auto; width:240px; max-width:80%; border-radius:14px; }
        .kt-pay { text-align:center; font-size:1rem; color:#3B2407; margin:10px 4px; }
        .kt-footnote { text-align:center; font-style:italic; font-size:0.8rem; color:#8a6d4b; margin:12px 4px; }
        .stButton > button { background-color:#8B4513; color:#FFF8F0; border:none;
            border-radius:12px; font-weight:700; }
        .stButton > button:hover { background-color:#6F360F; color:#fff; }
        .stButton > button:disabled { background-color:#c9b39c; color:#f3ece2; }
        .kt-footer { text-align:center; font-size:0.8rem; color:#8B4513; opacity:0.85; margin-top:22px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    st.markdown(f'<div class="kt-title">🍞 {SHOP_NAME}</div>', unsafe_allow_html=True)
    st.markdown('<div class="kt-tagline">Fresh bakery bread, right in Hall 16.</div>',
                unsafe_allow_html=True)


def render_footer():
    st.markdown('<div class="kt-footer">Made with ❤️ in Hall 16, NTU</div>',
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Customer order page
# ---------------------------------------------------------------------------
def render_order_page():
    data = load_data()
    price = float(data["price"])
    left = available_qty(data)
    can_order = data["is_open"] and left > 0

    b64 = img_to_base64(HERO_IMAGE)
    if b64:
        st.markdown(f'<img class="kt-hero" src="data:image/png;base64,{b64}" alt="Bread">',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="kt-hero-placeholder">🍞 Bakery Bread</div>',
                    unsafe_allow_html=True)

    st.markdown(f'<div class="kt-price"><b>{money(price)}</b> per bread</div>',
                unsafe_allow_html=True)

    st.markdown(
        f'<div class="kt-info">📍 <b>Meet-up:</b> {MEETUP_POINT}<br>'
        f'⏰ <b>Time:</b> {MEETUP_TIME}<br>'
        f'📅 <b>Days:</b> {MEETUP_DAYS}<br>'
        f'⚠️ While stock lasts!</div>',
        unsafe_allow_html=True,
    )

    if not data["is_open"]:
        st.markdown('<div class="kt-banner-closed">🔒 Shop is closed right now. '
                    f'See you {MEETUP_DAYS}!</div>', unsafe_allow_html=True)
    elif left <= 0:
        st.markdown('<div class="kt-banner-closed">😢 Sold out for tonight! '
                    'Try again next time.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="kt-banner-open">✅ Shop is OPEN — only {left} '
                    f'bread{"s" if left != 1 else ""} left!</div>', unsafe_allow_html=True)

    disabled = not can_order
    max_qty = max(1, min(MAX_PER_ORDER, left))

    with st.container(border=True):
        st.markdown('<div class="kt-section-label">How many breads?</div>',
                    unsafe_allow_html=True)
        qty = st.number_input("Quantity", min_value=1, max_value=max_qty, value=1,
                              step=1, disabled=disabled)

    with st.container(border=True):
        st.markdown('<div class="kt-section-label">Your details</div>',
                    unsafe_allow_html=True)
        name = st.text_input("Name", key="cust_name", disabled=disabled)
        contact = st.text_input(
            "Telegram @handle",
            key="cust_contact",
            placeholder="@yourhandle",
            help="We'll message you on Telegram when your bread is ready.",
            disabled=disabled,
        )
        special = st.text_input("Notes (optional)", key="special", disabled=disabled)

    total = round(price * qty, 2)
    st.markdown(
        f'<div class="kt-total"><div class="kt-total-row"><span>{qty} x bread @ '
        f'{money(price)}</span><span>{money(total)}</span></div>'
        f'<div class="kt-total-final"><span>Total</span><span>{money(total)}</span></div></div>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<div class="kt-section-label">💸 Pay by PayLah!</div>',
                    unsafe_allow_html=True)
        st.markdown(f"1. Copy the number below and PayLah! **{money(total)}** to it:")
        st.code(PAYLAH_NUMBER.replace(" ", ""), language=None)
        st.markdown("2. Screenshot your payment and upload it here:")
        proof = st.file_uploader("Payment screenshot", type=["png", "jpg", "jpeg", "webp"],
                                 key="proof", disabled=disabled,
                                 label_visibility="collapsed")

    if st.button("✅ Place My Order", type="primary", use_container_width=True,
                 disabled=disabled):
        handle = clean_handle(contact)
        if not name.strip():
            st.error("Please enter your name.")
            return
        if not handle:
            st.error("Please enter a valid Telegram handle, e.g. @yourhandle.")
            return
        if proof is None:
            st.error("Please upload a screenshot of your PayLah! payment.")
            return

        def place(d):
            if not d["is_open"]:
                return None, "Sorry, the shop just closed."
            if available_qty(d) < qty:
                return None, f"Sorry, only {available_qty(d)} left now. Please lower the quantity."
            p = float(d["price"])
            order = {
                "id": d["next_id"], "name": name.strip(), "contact": handle,
                "qty": int(qty), "price": p, "total": round(p * qty, 2),
                "special": special.strip(), "status": "pending",
                "time": now_sgt().strftime("%d %b %I:%M %p"),
            }
            order["proof"] = save_proof(order["id"], proof)
            d["next_id"] += 1
            d["orders"].append(order)
            return order, None

        order, err = update_data(place)
        if err:
            st.error(err)
            return
        notify_owner(order)
        st.session_state.order = order
        st.session_state.submitted = True
        st.rerun()


def render_confirmation():
    o = st.session_state.order
    st.markdown(f'<div class="kt-banner-open">✅ Order #{o["id"]} received — '
                'thank you!</div>', unsafe_allow_html=True)

    rows = [("Order", f"#{o['id']}"), ("Bread", f"{o['qty']} x {money(o['price'])}"),
            ("Name", o["name"]), ("Telegram", o["contact"]),
            ("Collect at", MEETUP_POINT), ("Time", MEETUP_TIME)]
    if o["special"]:
        rows.append(("Notes", o["special"]))
    rows_html = "".join(
        f'<div class="kt-total-row"><span style="color:#8a6d4b">{k}</span>'
        f'<span style="font-weight:600;text-align:right">{v}</span></div>' for k, v in rows)
    st.markdown(f'<div class="kt-summary"><div class="kt-summary-title">📋 Order Summary</div>'
                f'{rows_html}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="kt-total"><div class="kt-total-final"><span>Total</span>'
                f'<span>{money(o["total"])}</span></div></div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="kt-pay">We got your payment screenshot. 🙌<br>'
        'We\'ll check it and message you on <b>Telegram</b> when it\'s confirmed.</div>',
        unsafe_allow_html=True,
    )

    if st.button("🔄 Place Another Order", use_container_width=True):
        for k in ["cust_name", "cust_contact", "special", "order", "proof"]:
            st.session_state.pop(k, None)
        st.session_state.submitted = False
        st.rerun()


# ---------------------------------------------------------------------------
# Boss page  (open with ?boss at the end of the URL)
# ---------------------------------------------------------------------------
def render_proof(o):
    """Show the payment screenshot with a delete button (boss page)."""
    fname = o.get("proof")
    if not fname or not os.path.exists(os.path.join(PROOF_DIR, fname)):
        return
    with st.expander("🧾 Payment screenshot"):
        st.image(os.path.join(PROOF_DIR, fname))
        if st.button("🗑️ Delete picture", key=f"delproof_{o['id']}", use_container_width=True):
            def rm(d, oid=o["id"]):
                for x in d["orders"]:
                    if x["id"] == oid:
                        delete_proof(x.get("proof"))
                        x["proof"] = None
            update_data(rm)
            st.rerun()


def render_boss_page():
    st.markdown('<div class="kt-section-label" style="text-align:center;font-size:1.4rem">'
                '👑 Boss Page</div>', unsafe_allow_html=True)

    password = get_secret("BOSS_PASSWORD")
    if not password:
        st.error("Set BOSS_PASSWORD in your Streamlit secrets to use the boss page.")
        return
    if not st.session_state.get("boss_ok"):
        pw = st.text_input("Password", type="password", key="boss_pw")
        if st.button("Log in", use_container_width=True):
            if pw == password:
                st.session_state.boss_ok = True
                st.rerun()
            else:
                st.error("Wrong password.")
        return

    data = load_data()
    pending = [o for o in data["orders"] if o["status"] == "pending"]
    paid = [o for o in data["orders"] if o["status"] == "paid"]  # paid, not yet collected
    collected = [o for o in data["orders"] if o["status"] == "collected"]

    # --- Shop status
    with st.container(border=True):
        st.markdown('<div class="kt-section-label">Shop status</div>', unsafe_allow_html=True)
        if data["is_open"]:
            st.success("🟢 Shop is OPEN")
            if st.button("🔒 Close shop", use_container_width=True):
                update_data(lambda d: d.update(is_open=False))
                st.rerun()
        else:
            st.error("🔴 Shop is CLOSED")
            if st.button("🔓 Open shop", use_container_width=True):
                update_data(lambda d: d.update(is_open=True))
                st.rerun()

    # --- Stock & price
    with st.container(border=True):
        st.markdown('<div class="kt-section-label">Stock & price</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Stock", int(data["stock"]))
        c2.metric("Waiting pay", reserved_qty(data))
        c3.metric("Can sell", available_qty(data))
        new_stock = st.number_input("Set stock (breads you have now)", min_value=0,
                                    value=int(data["stock"]), step=1)
        new_price = st.number_input("Set price ($)", min_value=0.0,
                                    value=float(data["price"]), step=0.10,
                                    format="%.2f")
        if st.button("💾 Save stock & price", use_container_width=True):
            update_data(lambda d: d.update(stock=int(new_stock),
                                           price=round(float(new_price), 2)))
            st.success("Saved!")
            st.rerun()

    # --- Pending orders
    with st.container(border=True):
        st.markdown(f'<div class="kt-section-label">🧾 Check payment ({len(pending)})</div>',
                    unsafe_allow_html=True)
        if not pending:
            st.caption("No payments to check.")
        for o in pending:
            st.markdown(f"**#{o['id']} · {o['name']}** — {o['qty']} x bread · "
                        f"**{money(o['total'])}**  \n[{o['contact']}]({tg_link(o['contact'])})"
                        f" · {o['time']}"
                        + (f"  \n📝 {o['special']}" if o["special"] else ""))
            render_proof(o)
            b1, b2 = st.columns(2)
            if b1.button("💰 Payment collected", key=f"paid_{o['id']}",
                         use_container_width=True):
                def mark_paid(d, oid=o["id"]):
                    for x in d["orders"]:
                        if x["id"] == oid and x["status"] == "pending":
                            x["status"] = "paid"
                            d["stock"] = max(0, int(d["stock"]) - x["qty"])
                update_data(mark_paid)
                st.rerun()
            if b2.button("❌ Cancel", key=f"cancel_{o['id']}", use_container_width=True):
                def cancel(d, oid=o["id"]):
                    for x in d["orders"]:
                        if x["id"] == oid and x["status"] == "pending":
                            x["status"] = "cancelled"
                            delete_proof(x.get("proof"))
                            x["proof"] = None
                update_data(cancel)
                st.rerun()
            st.divider()

    # --- Paid orders (send confirmation)
    with st.container(border=True):
        st.markdown(f'<div class="kt-section-label">📦 To collect ({len(paid)} people · '
                    f'{sum(o["qty"] for o in paid)} breads)</div>', unsafe_allow_html=True)
        if not paid:
            st.caption("Nobody waiting to collect.")
        for o in paid:
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.markdown(f"**{o['name']}** — {o['qty']} bread{'s' if o['qty'] != 1 else ''}  \n"
                        f"[{o['contact']}]({tg_link(o['contact'])}) · #{o['id']}")
            if c2.button("✅ Collected", key=f"collect_{o['id']}", use_container_width=True):
                def mark_collected(d, oid=o["id"]):
                    for x in d["orders"]:
                        if x["id"] == oid and x["status"] == "paid":
                            x["status"] = "collected"
                update_data(mark_collected)
                st.rerun()
            with st.expander("📲 Confirmation message to copy"):
                st.code(confirm_text(o), language=None)
            render_proof(o)

    # --- Tonight's summary
    sold = paid + collected
    if sold:
        st.caption(f"Tonight: {sum(o['qty'] for o in sold)} breads sold · "
                   f"{money(sum(o['total'] for o in sold))} received · "
                   f"{len(collected)} collected, {len(paid)} still to collect")

    # --- Reset for next night
    with st.expander("🧹 Start a new night (clear all orders)"):
        st.caption("Removes all orders from the list. Stock and price stay as they are.")
        if st.button("Clear orders", use_container_width=True):
            def clear(d):
                for x in d["orders"]:
                    delete_proof(x.get("proof"))
                d["orders"] = []
            update_data(clear)
            st.rerun()

    if st.button("Log out", use_container_width=True):
        st.session_state.boss_ok = False
        st.rerun()


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------
def main():
    inject_css()
    render_header()
    if "boss" in st.query_params:
        render_boss_page()
    elif st.session_state.get("submitted", False):
        render_confirmation()
    else:
        render_order_page()
    render_footer()


main()
