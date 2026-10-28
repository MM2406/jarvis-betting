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
Nutze Google Search, um die finalen Spielergebnisse, Torschützen, Torstatistiken und Handicaps/Spreads für folgende Fussballwetten (inkl. europäische Ligen & MLS) zu recherchieren und exakt auszuwerten:

Offene Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Prüfe via Google Search, ob alle Spiele bereits beendet sind oder ob Partien noch anstehen / laufen oder verschoben wurden.
2. Prüfe 1X2, Over/Under, Asian Handicaps / Spreads und Torschützen-Picks exakt.
3. Markiere beendete Tipps mit ✅ WON, ❌ LOST oder 🟡 PUSH/VOID.
4. Noch nicht gespielte oder laufende Tipps markierst du mit ⏳ OFFEN / IN PROGRESS.
5. Ein Kombi-Ticket ist nur ✅ WON, wenn ausnahmslos alle Tipps des Tickets gewonnen haben.
6. Berechne Netto-Units (Einsatz 1.00 Unit pro Schein).
7. Berechne die genauen Metriken für das Performance Dashboard:
   - Ticket Win-Rate: (Gewonnene Tickets / Abgerechnete Tickets) in % inkl. 10-Segment Fortschrittsbalken (z.B. [🟩🟩🟩🟩🟩🟩🟩⬜⬜⬜])
   - Pick Hit-Rate: (Richtige Einzeltipps / Alle gespielten Einzeltipps) in % inkl. 10-Segment Fortschrittsbalken
   - Einsatz / Rückzahlung in Units
   - Netto-Profit / Verlust
   - ROI (Yield) in % = (Netto-Profit / Gesamteinsatz) * 100

WICHTIGE STATUS-ZEILE AM ENDE:
Falls noch mindestens ein Spiel offen oder in Progress ist (z. B. späte MLS-Nachtspiele oder Dienstags-/Mittwochsspiele), schreibe ganz am Ende exakt:
---STATUS: INCOMPLETE---
Wenn ausnahmslos ALLE Spiele und Picks endgültig abgeschlossen sind, schreibe ganz am Ende exakt:
---STATUS: COMPLETE---

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>⚽ JARVIS SOCCER SETTLEMENT & RECAP</b>
<i>Abrechnung der Wetten vom {data.get('date', datetime.now(LOCAL_TZ).strftime('%d.%m.%Y'))}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY:</b> [Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>SOCCER BANKER TICKET:</b> [Status]
[Picks & Resultate]

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC GOALS & BTTS VALUE TICKET:</b> [Status]
[Jeden Pick auflisten mit Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC MULTI-LEAGUE VALUE TICKET:</b> [Status]
[Jeden Pick auflisten mit Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
4. <b>VALUE TORSCHÜTZE / SPECIAL:</b> [Status]
[Pick auswerten]

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
            print("Alle Soccer Wetten final beendet. pending_soccer.json gelöscht.")
        else:
            print("Noch Soccer Partien offen. pending_soccer.json bleibt erhalten.")
    except Exception as e:
        print(f"Fehler bei Soccer Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_soccer_bets()
