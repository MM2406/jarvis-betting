import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def send_telegram_message(text):
    base_url = "https://api.telegram.org/bot"
    url = f"{base_url}{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Telegram Fehler: {e}")

def settle_bets():
    file_path = "pending_soccer.json"
    if not os.path.exists(file_path):
        print("Keine pending_soccer.json gefunden. Nichts abzurechnen.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            pending_data = json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden von JSON: {e}")
            return

    prompt = f"""
Du bist der Auswertungs-Bot für Fußballwetten. Hier sind die Tipps des letzten Spieltags:
{json.dumps(pending_data, ensure_ascii=False, indent=2)}

AUFGABE:
1. Prüfe die tatsächlichen Endergebnisse der aufgelisteten Partien.
2. Bestimme für jeden Schein ('potd', 'banker', 'goals_ticket', 'multi_ticket', 'scorer'), ob er GEWONNEN (WON) oder VERLOREN (LOST) hat.
3. Berechne den Kassensturz mit jeweils 1.0 Unit Einsatz pro Schein:
   - Gewinn = Quote - 1.0
   - Verlust = -1.0 Unit
4. Formatiere das Ergebnis in Telegram-HTML (<b>fett</b>, <i>kursiv</i>):

<b>📊 JARVIS FOOTBALL ABRECHNUNG & KASSENSTURZ</b>
<i>Datum: {pending_data.get('date', 'Spieltag')}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>Pick of the Day:</b> [WON / LOST] (Quote: X.XX)
1. <b>Banker-Doppelchance:</b> [WON / LOST] (Quote: X.XX)
2. <b>Goals & BTTS:</b> [WON / LOST] (Quote: X.XX)
3. <b>Multi-League Ticket:</b> [WON / LOST] (Quote: X.XX)
4. <b>Scorer / Special:</b> [WON / LOST] (Quote: X.XX)

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>Bilanz:</b> [X]W - [Y]L
<b>Netto-Ergebnis:</b> [+/-X.XX] Units
<b>ROI:</b> [+/-X.X]%
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        report = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        send_telegram_message(report)
        print("Abrechnung erfolgreich versendet.")
        
        # Leere oder archiviere die Datei nach Abrechnung
        os.remove(file_path)
    except Exception as e:
        print(f"Abrechnungsfehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_bets()
