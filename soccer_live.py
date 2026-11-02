import os
import sys
import json
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Sichere Anbindung der zentralen Telegram-Hilfsfunktion
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

STATE_FILE = "pending_soccer.json"
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
        print("[SoccerLive] Telegram Credentials fehlen.")
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
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200 or "message is not modified" in res.text:
            return True
        payload.pop("parse_mode", None)
        res2 = requests.post(url, json=payload, timeout=20)
        return res2.status_code == 200 or "message is not modified" in res2.text
    except Exception as e:
        print(f"[SoccerLive] Telegram Edit Ausnahme: {e}")
        return False

def fetch_live_football_events():
    """Ruft alle aktuell laufenden Fussballspiele weltweit über SportAPI ab."""
    if not RAPIDAPI_KEY:
        print("[SoccerLive] RAPIDAPI_KEY fehlt.")
        return []

    url = "https://sportapi7.p.rapidapi.com/api/v1/sport/football/events/live"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }
    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            return res.json().get("events", [])
        else:
            print(f"[SportAPI Soccer] HTTP {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[SportAPI Soccer Error] {e}")
    return []

def run_soccer_live():
    state = load_state()
    if not state:
        print("[SoccerLive] Keine pending_soccer.json vorhanden.")
        return

    msg_id = state.get("message_id")
    if not msg_id:
        print("[SoccerLive] Keine message_id in pending_soccer.json hinterlegt.")
        return

    raw_text = state.get("original_text", "")
    if not raw_text:
        print("[SoccerLive] Kein original_text hinterlegt.")
        return

    # Sammle alle einzigartigen Matches aus POTD und Tickets
    matches_to_track = set()
    if "potd" in state and isinstance(state["potd"], dict):
        m = state["potd"].get("match")
        if m:
            matches_to_track.add(m)

    for ticket in state.get("tickets", []):
        for pick in ticket.get("picks", []):
            m = pick.get("match")
            if m:
                matches_to_track.add(m)

    if not matches_to_track:
        print("[SoccerLive] Keine Spiele im Tracking-JSON gefunden.")
        return

    live_events = fetch_live_football_events()
    live_status_lines = []

    for match in sorted(matches_to_track):
        parts = [p.strip().lower() for p in re.split(r"vs\.?| - ", match, flags=re.IGNORECASE) if len(p.strip()) > 3]
        matched_ev = None

        for ev in live_events:
            h = ev.get("homeTeam", {}).get("name", "").lower()
            a = ev.get("awayTeam", {}).get("name", "").lower()
            if any(p in h or p in a for p in parts):
                matched_ev = ev
                break

        if matched_ev:
            h_score = matched_ev.get("homeScore", {}).get("current", 0)
            a_score = matched_ev.get("awayScore", {}).get("current", 0)
            status_desc = matched_ev.get("status", {}).get("description", "Live")
            live_status_lines.append(f"• <b>{match}:</b> <b>{h_score}:{a_score}</b> ({status_desc})")

    if not live_status_lines:
        print("[SoccerLive] Aktuell läuft keine der getrackten Soccer-Partien.")
        return

    live_block = (
        "⏱️ <b>LIVE-ZWISCHENSTÄNDE</b>\n" +
        "\n".join(live_status_lines)
    )

    pattern = r"⏱️ <b>LIVE-ZWISCHENSTÄNDE.*?(\n━━━━━━━━━━━━━━━━━━━━|\Z)"
    if re.search(pattern, raw_text, flags=re.DOTALL):
        new_text = re.sub(pattern, f"{live_block}\\1", raw_text, count=1, flags=re.DOTALL)
    else:
        new_text = raw_text.rstrip() + "\n\n━━━━━━━━━━━━━━━━━━━━\n" + live_block

    if new_text.strip() != raw_text.strip():
        if edit_telegram(msg_id, new_text):
            state["original_text"] = new_text
            save_state(state)
            print("[SoccerLive] Soccer-Ticket in Telegram erfolgreich live aktualisiert.")

if __name__ == "__main__":
    run_soccer_live()
