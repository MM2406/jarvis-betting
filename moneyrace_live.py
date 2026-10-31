import os
import sys
import json
import re
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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return False

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
        if res.status_code == 200:
            return True

        err_resp = res.json()
        err_desc = err_resp.get("description", "")

        # Wenn der Text identisch ist, ignoriert Telegram den Edit (kein echter Fehler)
        if "message is not modified" in err_desc:
            return True

        # Fallback auf Plaintext bei HTML-Formatierungsfehlern
        payload.pop("parse_mode", None)
        res2 = requests.post(url, json=payload, timeout=25)
        if res2.status_code == 200 or "message is not modified" in res2.text:
            return True

        print(f"Telegram Edit fehlgeschlagen: {res.text}")
        return False
    except Exception as e:
        print(f"Telegram Edit Ausnahme: {e}")
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
        print("Keine message_id hinterlegt.")
        return

    raw_text = active.get("original_text", "")
    if not raw_text:
        print("Kein Ausgangstext für das Ticket hinterlegt.")
        return

    match_name = active.get("match", "")
    match_date = active.get("date", "")
    pick_text = active.get("pick", "")
    now_berlin = datetime.now(LOCAL_TZ).strftime("%H:%M Uhr")

    print(f"Prüfe Live-Status für: {match_name} (Aktuelle Uhrzeit: {now_berlin})...")

    prompt = f"""
Du bist ein automatisierter Live-Sport-Tracker.
Recherchiere via Google Search den ECHTEN LIVE-SPIELSTAND für dieses Match:
- Begegnung: {match_name}
- Datum: {match_date}
- Geplanter Beginn: {active.get('time', '14:00 Uhr')}
- Aktuelle Uhrzeit: {now_berlin} (Europe/Berlin)
- Wette: {pick_text}

SUCH-ANWEISUNG:
Suche nach "{match_name} live score", "{match_name} sofascore" oder "{match_name} flashscore".
Wenn der Anpfiff um 14:00 Uhr war und es jetzt nach 14:00 Uhr ist, läuft das Spiel mit sehr hoher Wahrscheinlichkeit bereits oder ist in der Halbzeit! 
Antworte keinesfalls mit UPCOMING, es sei denn, das Spiel wurde offiziell verschoben.

ERMITTLE:
1. STATUS: 
   - 'LIVE' (falls Spiel aktuell läuft oder Halbzeitpause ist)
   - 'FINISHED' (falls Spiel abgepfiffen wurde)
   - 'UPCOMING' (NUR falls es nachweislich noch nicht angepfiffen wurde)
2. MINUTE: Aktuelle Spielminute (z.B. 25, 45, 60, 85). Falls Halbzeitpause, gib 45 an. Bei FINISHED 90.
3. SCORE: Exakter aktueller Spielstand (z.B. '0:0', '1:0', '1:2').
4. ASSESSMENT: 
   - 'ON_TRACK' (wenn der Tipp aktuell gewinnt oder Unentschieden bei Favorit)
   - 'AT_RISK' (wenn der Tipp aktuell verlieren würde)

Antworte STRIKT in diesem 4-Zeilen-Format:
STATUS: LIVE
MINUTE: 35
SCORE: 0:0
ASSESSMENT: ON_TRACK
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

        ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"Gemini Antwort:\n{ans}")

        status = "UPCOMING"
        minute = 0
        score = "-"
        track = "ON_TRACK"

        for line in ans.split("\n"):
            line = line.strip()
            if line.startswith("STATUS:"):
                status = line.replace("STATUS:", "").strip().upper()
            elif line.startswith("MINUTE:"):
                try:
                    minute = int(re.search(r'\d+', line).group())
                except:
                    minute = 45 if status == "LIVE" else 0
            elif line.startswith("SCORE:"):
                score = line.replace("SCORE:", "").strip()
            elif line.startswith("ASSESSMENT:"):
                track = line.replace("ASSESSMENT:", "").strip().upper()

        if status == "UPCOMING":
            print("Spiel hat laut Recherche noch nicht begonnen.")
            return

        bar = make_minute_bar(minute)
        pct = int((min(minute, 90) / 90) * 100)
        track_icon = "🟢 Pick auf Kurs" if track == "ON_TRACK" else "🟡 Pick unter Druck"

        if status == "FINISHED":
            new_live_section = (
                f"⏱️ <b>LIVE-TRACKER • BEENDET</b>\n"
                f"[████████████] 100%\n"
                f"• <b>Endstand:</b> {score}\n"
                f"• <b>Status:</b> Spiel offiziell beendet"
            )
        else:
            minute_display = "Halbzeit" if minute == 45 and "halftime" in ans.lower() else f"{minute}. Min"
            new_live_section = (
                f"⏱️ <b>LIVE-TRACKER • SPIEL LÄUFT</b>\n"
                f"{bar} {pct}% ({minute_display})\n"
                f"• <b>Spielstand:</b> <b>{score}</b>\n"
                f"• <b>Trend:</b> {track_icon}"
            )

        # Robuster Regex-Austausch des LIVE-TRACKER-Blocks (ohne nachfolgende Abschnitte abzuschneiden)
        pattern = r"⏱️ <b>LIVE-TRACKER.*?(\n━━━━━━━━━━━━━━━━━━━━|\Z)"
        if re.search(pattern, raw_text, flags=re.DOTALL):
            new_text = re.sub(
                pattern,
                f"{new_live_section}\\1",
                raw_text,
                count=1,
                flags=re.DOTALL
            )
        else:
            new_text = raw_text.rstrip() + "\n\n━━━━━━━━━━━━━━━━━━━━\n" + new_live_section

        if new_text.strip() != raw_text.strip():
            success = edit_telegram(msg_id, new_text)
            if success:
                active["original_text"] = new_text
                save_state(state)
                print(f"Ticket erfolgreich editiert: Stand {score} ({minute}')")
            else:
                print("Telegram-Edit fehlgeschlagen.")
        else:
            print("Keine Textänderung erforderlich.")

    except Exception as e:
        print(f"Fehler im Live-Update: {e}")

if __name__ == "__main__":
    run_live_update()
