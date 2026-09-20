import os
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8616898795:AAHLdN1ApozJvJuE9vDbIlkGisV0QcFCTWU")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "7582896775"))
GH_PAT = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
REPO_NAME = os.environ.get("GITHUB_REPOSITORY", "vasiliykotov2013-star/fcsellbot")
DATA_FILE = os.path.join(os.path.dirname(__file__), "cloud_history.json")

# В GitHub Actions работаем 5 часов (18000 сек), затем перезапускаем следующий воркфлоу
IS_GHA = os.environ.get("GITHUB_ACTIONS") == "true"
MAX_RUNTIME = 18000 if IS_GHA else 999999999
POLL_INTERVAL = 8  # Опрос каждые 8 секунд (МГНОВЕННО, без 2-часовых задержек!)

class RealtimeCloudBot:
    def __init__(self):
        self.subscribers = {ADMIN_CHAT_ID}
        self.history = []
        self.last_update_id = 0
        self.last_snapshot = None
        self.catalog = {}
        self.session = requests.Session()
        self.load_history()

    def load_history(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def save_history(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def send_tg_message(self, chat_id, text):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
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
            self.send_tg_message(cid, text)
            time.sleep(0.15)

    def detect_server(self, title):
        norm = title.lower().strip()
        anarchy_kw = ["барон", "страж", "герой", "аспид", "сквид", "токенов", "токен"]
        survival_kw = ["премиум", "креатив", "админ", "модератор", "гл.админ", "создатель",
                       "основатель", "оператор", "властелин", "консоль", "сервер", "хелпер",
                       "fors", "команда", "менеджер", "меценат", "owner", "ключ"]
        skyblock_kw = ["skyblock", "скайблок", "остров"]
        for kw in anarchy_kw:
            if kw in norm: return "anarchy"
        for kw in survival_kw:
            if kw in norm: return "survival"
        for kw in skyblock_kw:
            if kw in norm: return "skyblock"
        return "other"

    def fetch_recent_payments(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        r = self.session.get("https://forscraft.net", headers=headers, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")

        nodes = soup.select(".payment-list .payment-id")
        payments = []
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d.%m.%Y")

        for node in nodes:
            t_el = node.find("div", class_="title")
            p_el = node.find("div", class_="player")
            pr_el = node.find("div", class_="price")

            title = t_el.get_text(strip=True) if t_el else "Товар"
            player = p_el.get_text(strip=True).lstrip("─-— ").strip() if p_el else "Игрок"
            if not player:
                player = "Аноним"

            price = 0
            if pr_el:
                digits = "".join(filter(str.isdigit, pr_el.get_text()))
                if digits:
                    price = int(digits)

            server = self.detect_server(title)

            payments.append({
                "player": player,
                "title": title,
                "price": price,
                "server": server,
                "amount": 1,
                "timestamp": now_time,
                "date": now_date
            })

        curr_tuples = [(p["player"], p["title"], p["price"]) for p in payments]
        prev_tuples = [(p["player"], p["title"], p["price"]) for p in reversed(self.history[-60:])]

        if not prev_tuples:
            new_items = list(reversed(payments))
            return payments, new_items

        new_items = []
        matched_k = None
        for k in range(0, len(curr_tuples) + 1):
            suffix = curr_tuples[k:]
            prefix = prev_tuples[:len(suffix)]
            if suffix == prefix:
                matched_k = k
                break

        if matched_k is not None:
            new_items = list(reversed(payments[:matched_k]))
        else:
            new_items = list(reversed(payments))

        return payments, new_items

    def get_stats(self):
        srv = {"survival": 0, "anarchy": 0, "skyblock": 0, "other": 0}
        total = 0
        today_total = 0
        today_str = datetime.now().strftime("%d.%m.%Y")
        today_srv = {"survival": 0, "anarchy": 0, "skyblock": 0, "other": 0}

        for it in self.history:
            pr = int(it.get("price", 0))
            s = it.get("server", "other").lower()
            if s not in srv: s = "other"
            srv[s] += pr
            total += pr

            if it.get("date") == today_str:
                today_total += pr
                today_srv[s] += pr

        return {
            "total": total,
            "srv": srv,
            "today_total": today_total,
            "today_srv": today_srv,
            "today_date": today_str,
            "count": len(self.history)
        }

    def format_stats_msg(self):
        st = self.get_stats()
        t_srv = st["today_srv"]
        a_srv = st["srv"]
        return (
            f"📅 <b>СЕГОДНЯ ({st['today_date']}): {st['today_total']:,} руб</b>\n"
            f"  • Survival: {t_srv['survival']:,} руб\n"
            f"  • Anarchy: {t_srv['anarchy']:,} руб\n"
            f"  • SkyBlock: {t_srv['skyblock']:,} руб\n\n"
            f"⭐ <b>ВСЕ ДНИ (Всего): {st['total']:,} руб</b>\n"
            f"  • Survival: {a_srv['survival']:,} руб\n"
            f"  • Anarchy: {a_srv['anarchy']:,} руб\n"
            f"  • SkyBlock: {a_srv['skyblock']:,} руб\n"
            f"  • Всего покупок в базе: {st['count']} шт."
        )

    def handle_telegram_updates(self):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 1}
        try:
            r = self.session.get(url, params=params, timeout=5)
            data = r.json()
            if not data.get("ok"):
                return

            for upd in data.get("result", []):
                self.last_update_id = upd["update_id"]
                msg = upd.get("message")
                if not msg:
                    continue
                chat_id = msg.get("chat", {}).get("id")
                text = (msg.get("text") or "").strip()
                if not chat_id:
                    continue

                if text.startswith("/start"):
                    self.subscribers.add(chat_id)
                    welcome = (
                        "⚡ <b>ForsCraft Real-time Cloud Bot 24/7 АКТИВЕН!</b>\n\n"
                        "Оповещения приходят <b>моментально (каждые 8 секунд)</b> в реальном времени!\n\n"
                        f"{self.format_stats_msg()}\n\n"
                        "🔔 <b>Последние покупки:</b>"
                    )
                    self.send_tg_message(chat_id, welcome)
                    for it in self.history[-5:]:
                        msg_text = (
                            f"<b>{it['player']}</b> оплатил товар <b>{it['title']}</b>\n"
                            f"<i>(Сервер: {it['server'].upper()} | +{it['price']} руб | {it['timestamp']})</i>"
                        )
                        self.send_tg_message(chat_id, msg_text)
                        time.sleep(0.2)

                elif text.startswith("/today"):
                    self.subscribers.add(chat_id)
                    st = self.get_stats()
                    today_items = [it for it in self.history if it.get("date") == st['today_date']]
                    if not today_items:
                        self.send_tg_message(chat_id, f"📅 Сегодня ({st['today_date']}) пока не было покупок.")
                    else:
                        header = f"📅 <b>Покупки за сегодня ({st['today_date']}) — {len(today_items)} шт. на {st['today_total']:,} руб:</b>"
                        self.send_tg_message(chat_id, header)
                        for it in today_items[-10:]:
                            msg_text = (
                                f"<b>{it['player']}</b> оплатил товар <b>{it['title']}</b>\n"
                                f"<i>(Сервер: {it['server'].upper()} | +{it['price']} руб | {it['timestamp']})</i>"
                            )
                            self.send_tg_message(chat_id, msg_text)
                            time.sleep(0.2)

                elif text.startswith("/stats"):
                    self.subscribers.add(chat_id)
                    self.send_tg_message(chat_id, f"📊 <b>Сводка доходов ForsCraft:</b>\n\n{self.format_stats_msg()}")

                elif text.startswith("/all") or text.startswith("/purchases"):
                    self.subscribers.add(chat_id)
                    if not self.history:
                        self.send_tg_message(chat_id, "📭 История пока пуста.")
                    else:
                        self.send_tg_message(chat_id, f"📦 <b>Все покупки ({len(self.history)} шт.):</b>")
                        for it in self.history[-10:]:
                            msg_text = (
                                f"<b>{it['player']}</b> оплатил товар <b>{it['title']}</b>\n"
                                f"<i>(Сервер: {it['server'].upper()} | +{it['price']} руб | {it['timestamp']})</i>"
                            )
                            self.send_tg_message(chat_id, msg_text)
                            time.sleep(0.2)
        except Exception:
            pass

    def trigger_next_github_run(self):
        """Перезапускает следующий воркфлоу перед истечением лимита в 5 часов"""
        print(f"[{datetime.now()}] Triggering next GitHub Actions workflow run...")
        url = f"https://api.github.com/repos/{REPO_NAME}/actions/workflows/bot_runner.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {GH_PAT}",
            "Accept": "application/vnd.github+json"
        }
        try:
            r = requests.post(url, headers=headers, json={"ref": "main"}, timeout=10)
            print(f"[{datetime.now()}] Next run dispatched: status={r.status_code}")
        except Exception as e:
            print(f"[{datetime.now()}] Error dispatching next run: {e}")

    def run(self):
        start_time = time.time()
        print(f"[{datetime.now()}] Realtime Cloud Bot started. Polling every {POLL_INTERVAL}s (Max runtime: {MAX_RUNTIME}s)...")

        # Отправляем уведомление о старте моментального облачного мониторинга
        try:
            self.send_tg_message(
                ADMIN_CHAT_ID,
                "🚀 <b>ForsCraft Real-Time Cloud Bot 24/7 ВКЛЮЧЕН!</b>\n\n"
                "⚡ <b>Задержка: 0 секунд (опрос каждые 8 сек).</b>\n"
                "Все покупки с <code>forscraft.net</code> приходят моментально!\n"
                "Работает круглосуточно в облаке, ПК можно выключать."
            )
        except Exception:
            pass

        last_git_save = time.time()

        while True:
            elapsed = time.time() - start_time

            # 1. Проверяем новые покупки на forscraft.net
            try:
                current_payments, new_items = self.fetch_recent_payments()
                if new_items:
                    print(f"[{datetime.now()}] Found {len(new_items)} new purchases! Sending...")
                    for it in new_items:
                        self.history.append(it)
                        server_tag = it.get('server', 'other').upper()
                        msg = (
                            f"🛒 <b>{it['player']}</b> оплатил товар <b>«{it['title']}»</b> в кол-ве {it.get('amount', 1)}\n"
                            f"<i>Сервер: <b>{server_tag}</b> | <b>+{it['price']} руб</b> | {it['timestamp']} ({it['date']})</i>"
                        )
                        self.broadcast(msg)
                        time.sleep(0.2)

                    self.save_history()
            except Exception as e:
                print(f"[{datetime.now()}] Scrape error: {e}")

            # 2. Обрабатываем входящие команды Telegram (/today, /stats, /all)
            self.handle_telegram_updates()

            # 3. Каждые 15 минут сохраняем историю в Git
            if IS_GHA and (time.time() - last_git_save > 900):
                last_git_save = time.time()
                os.system('git add cloud_history.json && git diff --quiet && git diff --staged --quiet || (git commit -m "Save history [skip ci]" && git push) || true')

            # 4. Если подходим к 5 часам (в GitHub Actions) — запускаем следующий воркфлоу и выходим
            if elapsed >= (MAX_RUNTIME - 300):
                print(f"[{datetime.now()}] Reaching 5h limit. Handing over to next runner...")
                if IS_GHA:
                    self.trigger_next_github_run()
                    os.system('git add cloud_history.json && git diff --quiet && git diff --staged --quiet || (git commit -m "5h state save [skip ci]" && git push) || true')
                break

            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    bot = RealtimeCloudBot()
    bot.run()
