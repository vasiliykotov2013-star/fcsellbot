import os
import sys
import time
import json
import socket
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from bs4 import BeautifulSoup
import re

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8616898795:AAHLdN1ApozJvJuE9vDbIlkGisV0QcFCTWU")
DEFAULT_SUBSCRIBER = int(os.environ.get("ADMIN_CHAT_ID", "7582896775"))
PORT = int(os.environ.get("PORT", 8080))
DATA_FILE = "server_history.json"
SUBS_FILE = "server_subscribers.json"

class CloudScraper:
    def __init__(self, base_url="https://forscraft.net"):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.catalog = {}
        self.last_snapshot = None

    def fetch_page(self):
        resp = requests.get(self.base_url, headers=self.headers, timeout=12)
        resp.raise_for_status()
        return resp.text

    def update_catalog(self, soup):
        for item in soup.find_all("div", class_="item-id"):
            title_el = item.find("div", class_="title")
            server_el = item.find("input", attrs={"name": "server"})
            category_el = item.find("input", attrs={"name": "category"})
            purchase_el = item.find("input", attrs={"name": "purchase"})
            price_el = item.find("div", class_="price")

            if title_el and server_el:
                title = title_el.get_text(strip=True)
                server = server_el.get("value", "").strip() or "other"
                category = category_el.get("value", "").strip() if category_el else "other"
                purchase = purchase_el.get("value", "").strip() if purchase_el else ""

                price_text = price_el.get_text(strip=True) if price_el else "0"
                price_match = re.search(r'\d+', price_text)
                price = int(price_match.group(0)) if price_match else 0

                self.catalog[title.lower()] = {
                    "raw_title": title,
                    "server": server,
                    "category": category,
                    "purchase": purchase,
                    "price": price
                }

    def detect_server(self, title):
        norm_title = title.strip().lower()
        if norm_title in self.catalog:
            return self.catalog[norm_title]["server"]

        for cat_title, info in self.catalog.items():
            if cat_title in norm_title or norm_title in cat_title:
                return info["server"]

        anarchy_keywords = ["барон", "страж", "герой", "аспид", "сквид", "токенов", "токен"]
        survival_keywords = ["премиум", "креатив", "админ", "модератор", "гл.админ", "создатель",
                             "основатель", "оператор", "властелин", "консоль", "сервер", "хелпер",
                             "fors", "команда", "менеджер", "меценат", "owner", "ключ"]
        skyblock_keywords = ["skyblock", "скайблок", "остров"]

        for kw in anarchy_keywords:
            if kw in norm_title:
                return "anarchy"
        for kw in survival_keywords:
            if kw in norm_title:
                return "survival"
        for kw in skyblock_keywords:
            if kw in norm_title:
                return "skyblock"

        return "survival"

    def parse_recent_purchases(self, existing_history=None):
        html = self.fetch_page()
        soup = BeautifulSoup(html, "html.parser")
        self.update_catalog(soup)

        payment_nodes = soup.select(".payment-list .payment-id")
        current_payments = []
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d.%m.%Y")

        for node in payment_nodes:
            title_el = node.find("div", class_="title")
            player_el = node.find("div", class_="player")
            price_el = node.find("div", class_="price")

            title = title_el.get_text(strip=True) if title_el else "Товар"
            raw_player = player_el.get_text(strip=True) if player_el else "Игрок"
            player = raw_player.lstrip("─-— ").strip() or "Аноним"

            price_text = price_el.get_text(strip=True) if price_el else ""
            price_match = re.search(r'\d+', price_text)
            if price_match:
                price = int(price_match.group(0))
            else:
                cat_info = self.catalog.get(title.lower())
                price = cat_info["price"] if cat_info else 0

            server = self.detect_server(title)
            current_payments.append({
                "player": player,
                "title": title,
                "price": price,
                "server": server,
                "amount": 1,
                "timestamp": now_time,
                "date": now_date
            })

        curr_tuples = [(p["player"], p["title"], p["price"]) for p in current_payments]

        if existing_history is not None:
            prev_tuples = [(p["player"], p["title"], p["price"]) for p in reversed(existing_history[-60:])]
        elif self.last_snapshot is not None:
            prev_tuples = self.last_snapshot
        else:
            prev_tuples = []

        if not prev_tuples:
            new_items = list(reversed(current_payments))
            self.last_snapshot = curr_tuples
            return current_payments, new_items

        new_items = []
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

        self.last_snapshot = curr_tuples
        return current_payments, new_items

class CloudStorage:
    def __init__(self, filename=DATA_FILE):
        self.filename = filename
        self.history = []
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_purchases(self, items):
        for item in items:
            self.history.append(item)
        self.save()

    def get_stats(self):
        server_income = {"survival": 0, "anarchy": 0, "skyblock": 0, "duels": 0, "other": 0}
        total_income = 0
        for item in self.history:
            price = int(item.get("price", 0))
            server = item.get("server", "other").lower()
            if server not in server_income:
                server_income[server] = 0
            server_income[server] += price
            total_income += price
        return {
            "server_income": server_income,
            "total_income": total_income,
            "purchases_count": len(self.history)
        }

class CloudTelegramBot:
    def __init__(self, token=BOT_TOKEN):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session = requests.Session()
        self.subscribers = {DEFAULT_SUBSCRIBER}
        self.last_update_id = 0
        self.load_subscribers()

    def load_subscribers(self):
        if os.path.exists(SUBS_FILE):
            try:
                with open(SUBS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.subscribers.update(data)
            except Exception:
                pass

    def save_subscribers(self):
        try:
            with open(SUBS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self.subscribers), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_subscriber(self, chat_id):
        self.subscribers.add(chat_id)
        self.save_subscribers()

    def send_message(self, chat_id, text):
        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        for _ in range(3):
            try:
                r = self.session.post(url, json=payload, timeout=8)
                if r.status_code == 200 and r.json().get("ok"):
                    return True
                time.sleep(0.3)
            except Exception:
                time.sleep(0.3)
        return False

    def broadcast(self, text):
        for cid in list(self.subscribers):
            self.send_message(cid, text)
            time.sleep(0.15)

    def format_purchase_message(self, item):
        player = item.get("player", "Игрок")
        title = item.get("title", "Товар")
        amount = item.get("amount", 1)
        price = item.get("price", 0)
        server = item.get("server", "other").lower()
        time_str = item.get("timestamp", datetime.now().strftime("%H:%M"))
        return f"<b>{player}</b> оплатил товар <b>{title}</b> в количестве {amount}\n<i>(Сервер: {server.upper()} | +{price} руб | {time_str})</i>"

    def format_stats_message(self, stats):
        srv = stats.get("server_income", {})
        surv = srv.get("survival", 0)
        anar = srv.get("anarchy", 0)
        sky = srv.get("skyblock", 0)
        total = stats.get("total_income", 0)
        return (
            f"Доход сервера survival: {surv} руб\n"
            f"Доход сервера anarchy: {anar} руб\n"
            f"Доход сервера skyblock: {sky} руб\n"
            f"<b>Общий доход: {total} руб</b>"
        )

# Global instances
scraper = CloudScraper()
storage = CloudStorage()
bot = CloudTelegramBot()

def monitor_loop():
    print(f"[{datetime.now()}] 24/7 Cloud Monitor Loop Started...")
    while True:
        try:
            storage.load()
            current, new_items = scraper.parse_recent_purchases(storage.history)
            if new_items:
                storage.add_purchases(new_items)
                for item in new_items:
                    bot.broadcast(bot.format_purchase_message(item))
        except Exception as e:
            print(f"Scrape error: {e}")

        time.sleep(8)

def telegram_listener_loop():
    print(f"[{datetime.now()}] Telegram Listener Started...")
    while True:
        try:
            url = f"{bot.base_url}/getUpdates"
            params = {"offset": bot.last_update_id + 1, "timeout": 2}
            r = bot.session.get(url, params=params, timeout=6)
            data = r.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    bot.last_update_id = update["update_id"]
                    msg = update.get("message")
                    if not msg:
                        continue
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "").strip()

                    if not chat_id:
                        continue

                    if text.startswith("/start"):
                        bot.add_subscriber(chat_id)
                        stats_msg = bot.format_stats_message(storage.get_stats())
                        welcome = (
                            "👋 <b>ForsCraft Cloud Bot 24/7 подключен!</b>\n\n"
                            "Бот запущен на облачном сервере и работает <b>круглосуточно даже при выключенном ПК</b>!\n\n"
                            f"📊 <b>Текущий доход:</b>\n{stats_msg}\n\n"
                            "🔔 <b>Последние покупки:</b>"
                        )
                        bot.send_message(chat_id, welcome)
                        for it in storage.history[-6:]:
                            bot.send_message(chat_id, bot.format_purchase_message(it))
                            time.sleep(0.2)

                    elif text.startswith("/stats"):
                        bot.add_subscriber(chat_id)
                        stats_msg = bot.format_stats_message(storage.get_stats())
                        bot.send_message(chat_id, f"📊 <b>Сводка доходов ForsCraft:</b>\n\n{stats_msg}")

                    elif text.startswith("/all") or text.startswith("/purchases"):
                        bot.add_subscriber(chat_id)
                        if not storage.history:
                            bot.send_message(chat_id, "📭 История пока пуста.")
                        else:
                            bot.send_message(chat_id, f"📦 <b>Все покупки ({len(storage.history)} шт.):</b>")
                            for it in storage.history[-15:]:
                                bot.send_message(chat_id, bot.format_purchase_message(it))
                                time.sleep(0.2)
        except Exception as e:
            print(f"TG listener error: {e}")

        time.sleep(2)

# Healthcheck HTTP Server for Cloud platforms (Render, Koyeb, Railway)
class HealthcheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        stats = storage.get_stats()
        resp = {
            "status": "online",
            "bot": "@fcsell_bot",
            "subscribers": list(bot.subscribers),
            "stats": stats,
            "time": datetime.now().isoformat()
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass

def main():
    # Start monitor thread
    t1 = threading.Thread(target=monitor_loop, daemon=True)
    t1.start()

    # Start TG listener thread
    t2 = threading.Thread(target=telegram_listener_loop, daemon=True)
    t2.start()

    # Initial announcement
    try:
        init_stats = bot.format_stats_message(storage.get_stats())
        bot.send_message(
            DEFAULT_SUBSCRIBER,
            f"☁️ <b>ForsCraft Bot запущен на 24/7 сервере!</b>\n\n"
            f"Теперь бот работает непрерывно, даже когда ваш ПК выключен.\n\n"
            f"📊 <b>Текущий доход:</b>\n{init_stats}"
        )
    except Exception:
        pass

    # Start HTTP server on PORT
    server = HTTPServer(("0.0.0.0", PORT), HealthcheckHandler)
    print(f"HTTP healthcheck server running on port {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    main()
