import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Telegram Fehler: {e}")

def settle_bets():
    file_path = "pending_nhl.json"
    if not os.path.exists(file_path):
        print("Keine pending_nhl.json vorhanden.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            pending_data = json.load(f)
        except Exception as e:
            print(f"JSON-Ladefehler: {e}")
            return

    prompt = f"""
Du bist der Abrechnungs-Bot fuer NHL-Eishockeywetten. Hier sind die Tipps der letzten Nacht:
{json.dumps(pending_data, ensure_ascii=False, indent=2)}

AUFGABE:
1. Pruefe offizielle Endergebnisse (inkl. Overtime/Shootout) und die Boxscores (Tore, Scorerpunkte, Torschuesse).
2. Werte alle Scheine aus: 'potd', 'banker', 'puck_totals', 'player_props' -> WON oder LOST.
3. Begründe bei 'player_props' die Werte kurz (z.B. "McDavid: 4 Torschuesse (Line war Über 3.5) -> WON").
4. Berechne den Kassensturz mit 1.0 Unit Einsatz je Schein (Gewinn = Quote - 1.0; Verlust = -1.0 Unit).

FORMAT (Telegram-HTML):
<b>📊 JARVIS NHL ABRECHNUNG & KASSENSTURZ</b>
<i>Datum: {pending_data.get('date', 'Gestern')}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>Pick of the Day:</b> [WON / LOST] (Quote: X.XX)
1. <b>NHL Banker Double:</b> [WON / LOST] (Quote: X.XX)
2. <b>Puck Line & Totals:</b> [WON / LOST] (Quote: X.XX)
🎯 3. <b>Skater Props Double:</b> [WON / LOST] (Quote: X.XX)
   - [Spieler 1]: [Statistik -> WON/LOST]
   - [Spieler 2]: [Statistik -> WON/LOST]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>Bilanz:</b> [X]W - [Y]L
<b>Netto-Ergebnis:</b> [+/-X.XX] Units
<b>ROI:</b> [+/-X.X]%
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}

    try:
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        send_telegram_message(res.json()["candidates"][0]["content"]["parts"][0]["text"])
        os.remove(file_path)
        print("NHL Abrechnung versendet.")
    except Exception as e:
        print(f"Abrechnungsfehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_bets()
