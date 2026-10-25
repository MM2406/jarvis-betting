import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def send_telegram_message(text):
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
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        if TELEGRAM_THREAD_ID:
            try:
                payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
            except ValueError:
                pass

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

    prompt = f"""
Du bist 'JARVIS NHL SETTLEMENT AGENT'.
Recherchiere über Google Search die finalen Ergebnisse der NHL-Nacht (inkl. OT und Shootout) sowie die Boxscores (Torschützen, Assists, Shots on Goal) für folgende Wetten:

Offene NHL-Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Endergebnisse und Spieler-Statistiken (Tore, Assists, Shots) prüfen.
2. Markiere jeden Tipp mit ✅ WON, ❌ LOST oder 🟡 PUSH.
3. Ein Kombi-Ticket ist nur ✅ WON, wenn ausnahmslos alle Tipps des Tickets gewonnen haben.
4. Berechne Netto-Units (Einsatz 1.00 Unit pro Schein).

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏒 JARVIS NHL SETTLEMENT & RECAP</b>
<i>Abrechnung der NHL-Slate vom {data.get('date', datetime.now(LOCAL_TZ).strftime('%d.%m.%Y'))}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY:</b> [Ergebnis] -> [✅ WON / ❌ LOST]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NHL BANKER TICKET:</b> [✅ WON / ❌ LOST]
[Picks & Resultate]

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC TOTALS COMBO:</b> [✅ WON / ❌ LOST]
[Jeden Pick auflisten mit Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC PLAYER PROPS MULTI-TICKET:</b> [✅ WON / ❌ LOST]
[Für jeden Spieler: Name, Pick, tatsächliche Stats, Status ✅/❌]

<b>━━━━━━━━━━━━━━━━━━━━</b>
📈 <b>NHL TAGESBILANZ:</b> [Netto Profit/Loss in Units]
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        result_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        send_telegram_message(result_text)
        os.remove(file_path)
        print("NHL Wetten abgerechnet und pending_nhl.json gelöscht.")
    except Exception as e:
        print(f"Fehler bei NHL Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_nhl_bets()
