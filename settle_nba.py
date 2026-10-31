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

# Sichere Fallback-Kette für das NBA-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NBA", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")

def send_telegram_message(text):
    # Vorrangig zentralen Sender mit Hauptchat-Schutz nutzen
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_THREAD_NBA")

    # Autonomer Fallback
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine NBA Thread-ID vorhanden. Senden in Hauptchat blockiert.")
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

def settle_nba_bets():
    file_path = "pending_nba.json"
    if not os.path.exists(file_path):
        print("Keine offenen NBA Wetten gefunden (pending_nba.json fehlt).")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    prompt = f"""
Du bist 'JARVIS NBA SETTLEMENT AGENT'.
Recherchiere über Google Search die finalen Ergebnisse, Boxscores und individuellen Spielerstatistiken (Punkte, Rebounds, Assists, 3PM) der NBA für folgende Wetten:

Offene NBA-Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Prüfe, ob alle Spiele bereits beendet sind oder ob Partien noch anstehen / laufen oder verschoben wurden.
2. Markiere beendete Tipps mit ✅ WON, ❌ LOST oder 🟡 PUSH/VOID.
3. Noch nicht gespielte oder laufende Picks markierst du mit ⏳ OFFEN / IN PROGRESS.
4. Ein Kombi-Ticket ist nur ✅ WON, wenn ausnahmslos ALLE Picks im Ticket gewonnen haben.
5. Berechne Netto-Units (Einsatz 1.00 Unit pro Schein).
6. Berechne die genauen Metriken für das Performance Dashboard:
   - Ticket Win-Rate: (Gewonnene Tickets / Abgerechnete Tickets) in % inkl. 10-Segment Fortschrittsbalken (z.B. [🟩🟩🟩🟩🟩🟩🟩⬜⬜⬜])
   - Pick Hit-Rate: (Richtige Einzeltipps / Alle gespielten Einzeltipps) in % inkl. 10-Segment Fortschrittsbalken
   - Einsatz / Rückzahlung in Units
   - Netto-Profit / Verlust
   - ROI (Yield) in % = (Netto-Profit / Gesamteinsatz) * 100

WICHTIGE STATUS-ZEILE AM ENDE:
Falls noch mindestens ein Pick offen oder in Progress ist, schreibe ganz am Ende exakt:
---STATUS: INCOMPLETE---
Wenn ausnahmslos ALLE Spiele und Picks endgültig abgeschlossen sind, schreibe ganz am Ende exakt:
---STATUS: COMPLETE---

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏀 JARVIS NBA SETTLEMENT & RECAP</b>
<i>Abrechnung der NBA-Slate vom {data.get('date', datetime.now(LOCAL_TZ).strftime('%d.%m.%Y'))}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY:</b> [Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NBA BANKER TICKET:</b> [Status]
[Picks & Resultate]

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC TOTALS COMBO:</b> [Status]
[Jeden Pick auflisten mit Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC PLAYER PROPS MULTI-TICKET:</b> [Status]
[Für jeden Spieler: Name, Line, erzielte Stats, Status ✅/❌/⏳]

<b>━━━━━━━━━━━━━━━━━━━━</b>
📊 <b>PERFORMANCE DASHBOARD & METRIKEN</b>
• <b>Ticket Win-Rate:</b> [X]/[Y] ([Prozent]%) [Balken]
• <b>Pick Hit-Rate:</b>   [X]/[Y] ([Prozent]%) [Balken]
• <b>Einsatz / Return:</b> [Gesamteinsatz] U ➔ [Rückzahlung] U
• <b>Netto-Profit:</b>     [+/- Profit] Units
• <b>Tages-ROI:</b>        [+/- ROI]%
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
        raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]

        is_complete = "---STATUS: COMPLETE---" in raw_text
        clean_text = raw_text.replace("---STATUS: COMPLETE---", "").replace("---STATUS: INCOMPLETE---", "").strip()

        send_telegram_message(clean_text)

        if is_complete:
            os.remove(file_path)
            print("Alle NBA Wetten final beendet. pending_nba.json gelöscht.")
        else:
            print("Noch NBA Spiele/Props offen. pending_nba.json bleibt erhalten.")
    except Exception as e:
        print(f"Fehler bei NBA Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_nba_bets()
