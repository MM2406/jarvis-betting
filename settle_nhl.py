import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Sichere Anbindung an telegram_sender.py
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sichere Fallback-Kette für das NHL-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NHL", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram_message(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_THREAD_NHL")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine NHL Thread-ID vorhanden. Senden in Hauptchat blockiert.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3800
    chunks = []
    while len(text) > max_len:
        split_idx = text.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    if text:
        chunks.append(text)

    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "message_thread_id": int(TELEGRAM_THREAD_ID)
        }
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=20)
            if res2.status_code != 200:
                print(f"Telegram Fehler: {res2.text}")

def settle_nhl_bets():
    file_path = "pending_nhl.json"
    if not os.path.exists(file_path):
        print("Keine offenen NHL Wetten gefunden (pending_nhl.json fehlt).")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("pending_nhl.json ist leer. Keine Wetten zum Abrechnen.")
        return

    # Robuste Datumserkennung (verhindert 'list' object has no attribute 'get')
    date_display = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    if isinstance(data, dict):
        date_display = data.get("date", date_display)
    elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        d_val = data[0].get("date", "")
        if d_val:
            try:
                date_display = datetime.strptime(d_val, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                date_display = str(d_val)

    prompt = f"""
Du bist 'JARVIS NHL SETTLEMENT AGENT'.
Recherchiere über Google Search die finalen Ergebnisse der NHL (inkl. OT und Shootout) sowie die Boxscores (Torschützen, Assists, Shots on Goal) für folgende Wetten:

Offene NHL-Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Prüfe, ob alle Spiele beendet sind (FINAL). Tore + Assists = Punkte!
2. Markiere beendete Tipps mit ✅ WON, ❌ LOST oder 🟡 PUSH.
3. Bei Kombiwetten: Zeige jedes einzelne Bein (Leg) mit Ergebnis und Status (z.B. [✅] Team A, [❌] Team B).
4. Berechne Netto-Units (Einsatz: 1.00 Unit pro Wette/Schein).

Am Ende MUSS zwingend dieser maschinenlesbare JSON-Block folgen:
```json
{{
  "tickets_total": 4,
  "tickets_won": 3,
  "picks_total": 6,
  "picks_won": 5,
  "total_staked": 4.0,
  "total_returned": 5.91,
  "net_profit": 1.91,
  "roi": 47.75,
  "is_complete": true
}}
