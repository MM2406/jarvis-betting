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

def settle_soccer_bets():
    file_path = "pending_soccer.json"
    if not os.path.exists(file_path):
        print("Keine offenen Soccer Wetten gefunden (pending_soccer.json fehlt).")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    prompt = f"""
Du bist 'JARVIS SOCCER SETTLEMENT AGENT'.
Nutze Google Search, um die finalen Spielergebnisse, Torschützen und Statistiken für folgende Fussballwetten vom Spieltag zu recherchieren und exakt auszuwerten:

Offene Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Suche nach den tatsächlichen Endergebnissen der genannten Partien.
2. Markiere jeden Tipp mit ✅ WON, ❌ LOST oder 🟡 VOID/POSTPONED.
3. Berechne den Gewinn bzw. Verlust je Ticket bei fiktiven 1.00 Unit Einsatz pro Schein.
4. Berechne die gesamte Netto-Bilanz (Profit/Verlust in Units) für diesen Tag.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>📊 JARVIS SOCCER SETTLEMENT & RECAP</b>
<i>Abrechnung der Wetten vom {data.get('date', datetime.now(LOCAL_TZ).strftime('%d.%m.%Y'))}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY:</b> [Ergebnis] -> [✅ WON / ❌ LOST]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>SOCCER BANKER TICKET:</b> [✅ WON / ❌ LOST]
- [Spiel 1]: [Ergebnis & Status]
- [Spiel 2]: [Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>GOALS & BTTS VALUE TICKET:</b> [✅ WON / ❌ LOST]
[Picks auswerten]

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>MULTI-LEAGUE VALUE TICKET:</b> [✅ WON / ❌ LOST]
[Picks auswerten]

<b>━━━━━━━━━━━━━━━━━━━━</b>
4. <b>VALUE TORSCHÜTZE / SPECIAL:</b> [✅ WON / ❌ LOST]
[Pick auswerten]

<b>━━━━━━━━━━━━━━━━━━━━</b>
📈 <b>TAGESBILANZ:</b> [Netto Profit/Loss in Units]
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
        print("Soccer Wetten abgerechnet und pending_soccer.json gelöscht.")
    except Exception as e:
        print(f"Fehler bei Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_soccer_bets()
