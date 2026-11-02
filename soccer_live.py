import os
import sys
import json
import re
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

STATE_FILE = "pending_soccer.json"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

def make_progress_bar(current, total=90, length=10):
    """Erzeugt einen visuellen Unicode-Fortschrittsbalken."""
    pct = min(1.0, max(0.0, current / total))
    filled = int(round(pct * length))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(pct * 100)}%"

def get_match_minute(ev):
    """Ermittelt die Spielminute und den Status aus den SportAPI-Daten."""
    status = ev.get("status", {})
    desc = status.get("description", "").lower()

    if any(k in desc for k in ["ended", "finished", "ft", "aet", "pen"]):
        return 90, "Endstand", True
    if "halftime" in desc or "half time" in desc or "ht" in desc:
        return 45, "Halbzeit", False

    minute = status.get("minute") or ev.get("time", {}).get("minute")
    if minute and isinstance(minute, (int, float)):
        return int(minute), f"{int(minute)}'", False

    start_ts = ev.get("startTimestamp")
    if start_ts:
        now_ts = int(time.time())
        elapsed = (now_ts - start_ts) // 60
        if "2nd" in desc or "second" in desc:
            calc_min = min(90, max(46, elapsed - 15))
        else:
            calc_min = min(45, max(1, elapsed))
        return calc_min, f"{calc_min}'", False

    return 0, status.get("description", "Live"), False

def evaluate_pick_progress(pick_text, h_score, a_score, is_finished=False):
    """Ermittelt den Zwischen- oder Endstand einer Tor-/BTTS-Wette."""
    pt = pick_text.lower()
    total_goals = h_score + a_score

    # Über 2.5 Tore
    if "über 2.5" in pt or "over 2.5" in pt:
        if total_goals >= 3:
            return f"✅ {total_goals}/3 Tore"
        return f"❌ {total_goals}/3 Tore" if is_finished else f"⏳ {total_goals}/3 Tore"

    # Über 1.5 Tore
    if "über 1.5" in pt or "over 1.5" in pt:
        if total_goals >= 2:
            return f"✅ {total_goals}/2 Tore"
        return f"❌ {total_goals}/2 Tore" if is_finished else f"⏳ {total_goals}/2 Tore"

    # Beide Teams treffen (BTTS)
    if "beide" in pt or "btts" in pt:
        hit = (1 if h_score > 0 else 0) + (1 if a_score > 0 else 0)
        if hit == 2:
            return "✅ Beide getroffen"
        return f"❌ {hit}/2 Teams" if is_finished else f"⏳ {hit}/2 Teams"

    return None

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

    # Gespeicherte beendete Spiele laden (oder initialisieren)
    finished_matches = state.get("finished_matches", {})

    match_picks = {}
    if "potd" in state and isinstance(state["potd"], dict):
        m = state["potd"].get("match")
        p = state["potd"].get("pick")
        if m:
            match_picks.setdefault(m, []).append(f"⭐ POTD: {p}")

    for ticket in state.get("tickets", []):
        t_name = ticket.get("ticket_name", "Kombi")
        for p_item in ticket.get("picks", []):
            m = p_item.get("match")
            p = p_item.get("pick")
            if m:
                match_picks.setdefault(m, []).append(f"{t_name}: {p}")

    if not match_picks:
        print("[SoccerLive] Keine Spiele im Tracking-JSON gefunden.")
        return

    live_events = fetch_live_football_events()
    live_status_lines = []

    for match, picks in sorted(match_picks.items()):
        # 1. Prüfen, ob das Spiel bereits als beendet gespeichert wurde
        if match in finished_matches:
            f_data = finished_matches[match]
            h_score = f_data["h_score"]
            a_score = f_data["a_score"]
            progress_bar = make_progress_bar(90, total=90, length=10)

            pick_evals = []
            for pick_desc in picks:
                eval_str = evaluate_pick_progress(pick_desc, h_score, a_score, is_finished=True)
                if eval_str:
                    pick_evals.append(f"   ↳ {eval_str} ({pick_desc.split(':')[0]})")
            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""

            live_status_lines.append(
                f"🏁 <b>{match}</b> | <b>{h_score}:{a_score}</b> (Endstand)\n"
                f"   Zeit: <code>{progress_bar}</code>"
                f"{eval_block}"
            )
            continue

        # 2. Match in Live-Events suchen
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
            curr_min, min_label, is_finished = get_match_minute(matched_ev)

            if is_finished:
                # Dauerhaft im State sichern
                finished_matches[match] = {
                    "h_score": h_score,
                    "a_score": a_score,
                    "finished_at": datetime.now(LOCAL_TZ).isoformat()
                }
                state["finished_matches"] = finished_matches

            progress_bar = make_progress_bar(curr_min, total=90, length=10)

            pick_evals = []
            for pick_desc in picks:
                eval_str = evaluate_pick_progress(pick_desc, h_score, a_score, is_finished=is_finished)
                if eval_str:
                    pick_evals.append(f"   ↳ {eval_str} ({pick_desc.split(':')[0]})")

            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""
            icon = "🏁" if is_finished else "🔴"

            live_status_lines.append(
                f"{icon} <b>{match}</b> | <b>{h_score}:{a_score}</b> ({min_label})\n"
                f"   Zeit: <code>{progress_bar}</code>"
                f"{eval_block}"
            )

    if not live_status_lines:
        print("[SoccerLive] Aktuell weder aktive noch beendete Partien zum Anzeigen vorhanden.")
        return

    live_block = (
        "⏱️ <b>LIVE-TRACKER & FORTSCHRITT</b>\n" +
        "\n\n".join(live_status_lines)
    )

    pattern = r"⏱️ <b>LIVE-.*?(?=\n━━━━━━━━━━━━━━━━━━━━|\Z)"
    if re.search(pattern, raw_text, flags=re.DOTALL):
        new_text = re.sub(pattern, live_block, raw_text, count=1, flags=re.DOTALL)
    else:
        new_text = raw_text.rstrip() + "\n\n━━━━━━━━━━━━━━━━━━━━\n" + live_block

    if new_text.strip() != raw_text.strip():
        if edit_telegram(msg_id, new_text):
            state["original_text"] = new_text
            save_state(state)
            print("[SoccerLive] Soccer-Ticket in Telegram erfolgreich live aktualisiert.")
    else:
        # State speichern, falls Spiele als fertig markiert wurden
        save_state(state)

if __name__ == "__main__":
    run_soccer_live()
