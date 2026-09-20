import os
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8616898795:AAHLdN1ApozJvJuE9vDbIlkGisV0QcFCTWU")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "7582896775"))
DATA_FILE = os.path.join(os.path.dirname(__file__), "cloud_history.json")

def send_tg_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"}
    for _ in range(3):
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                return True
        except Exception:
            time.sleep(1)
    return False

def scrape_and_alert():
    # 1. Load existing history
    history = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    # 2. Fetch page
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    r = requests.get("https://forscraft.net", headers=headers, timeout=12)
    soup = BeautifulSoup(r.text, "html.parser")

    # 3. Parse items
    payment_nodes = soup.select(".payment-list .payment-id")
    current_payments = []
    now_time = datetime.now().strftime("%H:%M:%S")
    now_date = datetime.now().strftime("%d.%m.%Y")

    for node in payment_nodes:
        title_el = node.find("div", class_="title")
        player_el = node.find("div", class_="player")
        price_el = node.find("div", class_="price")

        title = title_el.get_text(strip=True) if title_el else "Товар"
        player = player_el.get_text(strip=True).lstrip("─-— ").strip() if player_el else "Игрок"
        if not player:
            player = "Аноним"

        price = 0
        if price_el:
            digits = "".join(filter(str.isdigit, price_el.get_text()))
            if digits:
                price = int(digits)

        current_payments.append({
            "player": player,
            "title": title,
            "price": price,
            "timestamp": now_time,
            "date": now_date
        })

    # 4. Detect new items
    curr_tuples = [(p["player"], p["title"], p["price"]) for p in current_payments]
    prev_tuples = [(p["player"], p["title"], p["price"]) for p in reversed(history[-50:])]

    new_items = []
    if not history:
        new_items = list(reversed(current_payments))
    else:
        matched_k = None
        for k in range(0, len(curr_tuples) + 1):
            suffix = curr_tuples[k:]
            prefix = prev_tuples[:len(suffix)]
            if suffix == prefix:
                matched_k = k
                break

        if matched_k is not None:
            new_items = list(reversed(current_payments[:matched_k]))
        else:
            new_items = list(reversed(current_payments))

    # 5. Alert & Save
    if new_items:
        print(f"[{datetime.now()}] Found {len(new_items)} new purchases! Sending alerts...")
        for it in new_items:
            history.append(it)
            msg = (
                f"🛒 <b>{it['player']}</b> оплатил товар <b>{it['title']}</b>\n"
                f"<i>(+{it['price']} руб | {it['timestamp']} {it['date']})</i>"
            )
            send_tg_message(msg)
            time.sleep(0.3)

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    else:
        print(f"[{datetime.now()}] No new purchases.")

if __name__ == "__main__":
    scrape_and_alert()
