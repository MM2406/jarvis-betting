import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = "moneyrace_state.json"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {STATE_FILE}: {e}")
        return None

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {STATE_FILE}: {e}")

def edit_telegram(message_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_id": int(message_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=25)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram Edit Fehler: {e}")
        return False

def make_minute_bar(minute, total=90):
    clamped = max(0, min(minute, total))
    blocks = int((clamped / total) * 12)
    return f"[{'█' * blocks}{'░' * (12 - blocks)}]"

def run_live_update():
    state = load_state()
    if not state or not state.get("active_pick"):
        print("Kein aktiver Pick für Live-Tracking vorhanden.")
        return

    active = state["active_pick"]
    msg_id = active.get("message_id")
    if not msg_id:
        print("Keine message_id hinterlegt. Eventuell wurde das Ticket manuell gepostet.")
        return

    raw_text = active.get("original_text", "")
    if not raw_text:
        print("Kein Ausgangstext für das Ticket hinterlegt.")
        return

    print(f"Prüfe Live-Status für: {active.get('match')}...")

    prompt = f"""
Recherchiere via Google Search den aktuellen Live-Status für diese Sportbegegnung:
Match: {active.get('match')}
Datum: {active.get('date')}
Tipp: {active.get('pick')}

Ermittle:
1. STATUS: Ist das Spiel noch nicht gestartet (UPCOMING), läuft es aktuell (LIVE) oder ist es beendet (FINISHED)?
2. MINUTE: Welche Spielminute läuft gerade (Zahl von 1 bis 95)? Falls Halbzeitpause, gib 45 an. Bei UPCOMING 0, bei FINISHED 90.
3. SCORE: Wie lautet der aktuelle Spielstand (z. B. 1:0)?
4. ASSESSMENT: Liegt der Tipp aktuell auf Kurs (ON_TRACK) oder ist er gefährdet (AT_RISK)?

Format:
STATUS: UPCOMING oder LIVE oder FINISHED
MINUTE: Zahl
SCORE: Spielstand
ASSESSMENT: ON_TRACK oder AT_RISK
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(url, json=payload, timeout=45)
        if res.status_code != 200:
            print(f"Gemini API Fehler: {res.status_code}")
            return

        ans = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        status = "UPCOMING"
        minute = 0
        score = "-"
        track = "ON_TRACK"

        for line in ans.split("\n"):
            line = line.strip()
            if line.startswith("STATUS:"):
                status = line.replace("STATUS:", "").strip()
            elif line.startswith("MINUTE:"):
                try:
                    minute = int(line.replace("MINUTE:", "").strip())
                except:
                    pass
            elif line.startswith("SCORE:"):
                score = line.replace("SCORE:", "").strip()
            elif line.startswith("ASSESSMENT:"):
                track = line.replace("ASSESSMENT:", "").strip()

        if status == "UPCOMING":
            print("Spiel hat noch nicht begonnen.")
            return

        bar = make_minute_bar(minute)
        pct = int((min(minute, 90) / 90) * 100)
        track_icon = "🟢 Pick auf Kurs" if track == "ON_TRACK" else "🟡 Pick unter Druck"

        if status == "FINISHED":
            live_block = (
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏱️ <b>LIVE-TRACKER • BEENDET</b>\n"
                f"[████████████] 100%\n"
                f"• <b>Endstand:</b> {score}\n"
                f"• <b>Status:</b> Reguläre Spielzeit beendet"
            )
        else:
            live_block = (
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏱️ <b>LIVE-TRACKER • SPIEL LÄUFT</b>\n"
                f"{bar} {pct}% ({minute}. Min)\n"
                f"• <b>Spielstand:</b> <b>{score}</b>\n"
                f"• <b>Trend:</b> {track_icon}"
            )

        # Alten Live-Tracker Block ersetzen oder anhängen
        if "⏱️ <b>LIVE-TRACKER" in raw_text:
            parts = raw_text.split("━━━━━━━━━━━━━━━━━━━━\n⏱️ <b>LIVE-TRACKER")
            base_part = parts[0].rstrip()
            new_text = base_part + "\n" + live_block
        else:
            new_text = raw_text.rstrip() + "\n\n" + live_block

        if new_text != raw_text:
            success = edit_telegram(msg_id, new_text)
            if success:
                active["original_text"] = new_text
                save_state(state)
                print(f"Ticket erfolgreich editiert: Stand {score} ({minute}')")
            else:
                print("Telegram-Edit fehlgeschlagen.")

    except Exception as e:
        print(f"Fehler im Live-Update: {e}")

if __name__ == "__main__":
    run_live_update()
