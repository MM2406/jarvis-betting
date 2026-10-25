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
    file_path = "pending_soccer.json"
    if not os.path.exists(file_path):
        # Fallback falls die Datei anders benannt wurde
        for alt in ["pending_bets.json", "pending_football.json"]:
            if os.path.exists(alt):
                file_path = alt
                break
        else:
            print("Keine anstehende Fussball-Wettendatei gefunden.")
            return

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            pending_data = json.load(f)
        except Exception as e:
            print(f"JSON-Ladefehler: {e}")
            return

    match_date = pending_data.get("date", "gestern")

    prompt = f"""
Du bist der offizielle Abrechnungs-Bot fuer Fussballwetten.
WICHTIGSTE REGEL: Nutze Google Search, um die ECHTEN Endergebnisse der Spiele vom {match_date} zu pruefen.
Behandle das angegebene Datum {match_date} als Gegenwart/Gestern. Nutze keinesfalls historische Partien aus vergangenen Jahren!

Hier sind die offenen Tipps:
{json.dumps(pending_data, ensure_ascii=False, indent=2)}

AUFGABE:
1. Suche per Websuche nach den offiziellen Endergebnissen jedes einzelnen Spiels vom {match_date}.
2. Werte alle Scheine im Datensatz aus ('potd', 'banker', 'goals', etc.) -> WON oder LOST.
   - Kombiwetten sind nur WON, wenn ALLE enthaltenen Tipps korrekt sind.
3. Berechne den Kassensturz mit 1.0 Unit Einsatz je Schein:
   - Bei WON: Netto-Gewinn = (Quote - 1.0)
   - Bei LOST: Verlust = -1.0 Unit
4. Erstelle die Gesamtabrechnung mit Bilanz (W - L), Netto-Units und ROI.

FORMAT-VORGABE (Telegram-HTML, keine Markdown-Sternderl im Text):
<b>📊 JARVIS FOOTBALL ABRECHNUNG & KASSENSTURZ</b>
<i>Spieltag: {match_date}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>Pick of the Day:</b> [WON / LOST] (Quote: X.XX)
[Werte hier alle weiteren im JSON vorhandenen Scheine auf:]
1. <b>[Scheinname]:</b> [WON / LOST] (Quote: X.XX)

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>Bilanz:</b> [X]W - [Y]L
<b>Netto-Ergebnis:</b> [+/-X.XX] Units
<b>ROI:</b> [+/-X.X]%
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        candidates = res.json().get("candidates", [])
        if candidates and "parts" in candidates[0]["content"]:
            out_text = candidates[0]["content"]["parts"][0]["text"]
            send_telegram_message(out_text)
            os.remove(file_path)
            print("Fussball Abrechnung erfolgreich abgeschlossen.")
        else:
            print("Keine Textantwort von Gemini erhalten.")
    except Exception as e:
        print(f"Abrechnungsfehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_bets()
