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
    file_path = "pending_nba.json"
    if not os.path.exists(file_path):
        print("Keine pending_nba.json vorhanden.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            pending_data = json.load(f)
        except Exception as e:
            print(f"JSON-Ladefehler: {e}")
            return

    match_date = pending_data.get("date", "gestern")

    prompt = f"""
Du bist der offizielle Abrechnungs-Bot fuer NBA-Wetten.
WICHTIGSTE REGEL: Nutze Google Search, um die ECHTEN Endergebnisse und Boxscores (Spielerstatistiken) der NBA-Spiele der letzten Nacht ({match_date}) zu pruefen.
Behandle das Datum {match_date} als Gegenwart/Gestern. Nutze keine veralteten historischen Spielplaene!

Hier sind die offenen Tipps:
{json.dumps(pending_data, ensure_ascii=False, indent=2)}

AUFGABE:
1. Suche per Websuche nach den offiziellen NBA-Endergebnissen und Boxscores der Partien.
2. Werte alle Scheine im Datensatz aus ('potd', 'banker', 'market_value', 'player_props', 'spread_totals', etc.) -> WON oder LOST.
   - Kombiwetten sind nur WON, wenn AUSNAHMSLOS ALLE enthaltenen Tipps/Spieler-Picks korrekt sind.
3. Begründe bei jedem Schein kurz das Ergebnis anhand der realen Punkte/Stats.
4. Berechne den Kassensturz mit 1.0 Unit Einsatz je Schein:
   - Bei WON: Netto-Gewinn = (Quote - 1.0)
   - Bei LOST: Verlust = -1.0 Unit
5. Erstelle die Gesamtabrechnung mit Bilanz (W - L), Netto-Units und ROI.

FORMAT-VORGABE (Telegram-HTML, keine Markdown-Sternderl im Text):
<b>📊 JARVIS NBA ABRECHNUNG & KASSENSTURZ</b>
<i>Datum: {match_date}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>Pick of the Day:</b> [WON / LOST] (Quote: X.XX)
- [Match/Tipp]: [Endergebnis] -> [WON / LOST]

1. <b>Banker Ticket:</b> [WON / LOST] (Quote: X.XX)
[Für jedes Spiel:]
- [Match/Tipp]: [Endergebnis] -> [WON / LOST]

2. <b>Market Value / Spread & Totals Ticket:</b> [WON / LOST] (Quote: X.XX)
[Für jedes Spiel:]
- [Match/Tipp]: [Endergebnis] -> [WON / LOST]

🎯 3. <b>Player Props Ticket:</b> [WON / LOST / ENTFÄLLT] (Quote: X.XX)
[Für jeden Spieler die realen Stats aufführen:]
- [Spieler]: [Punkte/Assists/Rebounds] -> [WON / LOST]

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
            print("NBA Abrechnung versendet.")
        else:
            print("Keine Textantwort von Gemini erhalten.")
    except Exception as e:
        print(f"Abrechnungsfehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_bets()
