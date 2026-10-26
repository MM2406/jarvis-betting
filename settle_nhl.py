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
Recherchiere über Google Search die finalen Ergebnisse der NHL (inkl. OT und Shootout) sowie die Boxscores (Torschützen, Assists, Shots on Goal) für folgende Wetten:

Offene NHL-Wetten:
{json.dumps(data, ensure_ascii=False, indent=2)}

REGELN:
1. Prüfe, ob alle Spiele bereits beendet sind oder ob Partien noch anstehen / laufen oder verschoben wurden.
2. Endergebnisse und Spieler-Statistiken (Tore, Assists, Shots) prüfen.
3. Markiere beendete Tipps mit ✅ WON, ❌ LOST oder 🟡 PUSH.
4. Noch nicht gespielte oder laufende Picks markierst du mit ⏳ OFFEN / IN PROGRESS.
5. Ein Kombi-Ticket ist nur ✅ WON, wenn ausnahmslos alle Tipps des Tickets gewonnen haben.
6. Berechne Netto-Units (Einsatz 1.00 Unit pro Schein).

WICHTIGE STATUS-ZEILE AM ENDE:
Falls noch mindestens ein Pick offen oder in Progress ist, schreibe ganz am Ende exakt:
---STATUS: INCOMPLETE---
Wenn ausnahmslos ALLE Spiele und Picks endgültig abgeschlossen sind, schreibe ganz am Ende exakt:
---STATUS: COMPLETE---

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏒 JARVIS NHL SETTLEMENT & RECAP</b>
<i>Abrechnung der NHL-Slate vom {data.get('date', datetime.now(LOCAL_TZ).strftime('%d.%m.%Y'))}</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY:</b> [Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NHL BANKER TICKET:</b> [Status]
[Picks & Resultate]

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC TOTALS COMBO:</b> [Status]
[Jeden Pick auflisten mit Ergebnis & Status]

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC PLAYER PROPS MULTI-TICKET:</b> [Status]
[Für jeden Spieler: Name, Pick, tatsächliche Stats, Status ✅/❌/⏳]

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
        raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        
        is_complete = "---STATUS: COMPLETE---" in raw_text
        clean_text = raw_text.replace("---STATUS: COMPLETE---", "").replace("---STATUS: INCOMPLETE---", "").strip()
        
        send_telegram_message(clean_text)

        if is_complete:
            os.remove(file_path)
            print("Alle NHL Wetten final beendet. pending_nhl.json gelöscht.")
        else:
            print("Noch NHL Spiele/Props offen. pending_nhl.json bleibt für den nächsten Run erhalten.")
    except Exception as e:
        print(f"Fehler bei NHL Settlement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    settle_nhl_bets()
