import os
import json
import requests

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

PENDING_FILE = "pending_soccer.json"

def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    if TELEGRAM_THREAD_ID:
        payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def run_lineup_check():
    if not os.path.exists(PENDING_FILE):
        print("Keine pending_soccer.json gefunden.")
        return

    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    # Alle relevanten Matches aus POTD und Tickets sammeln
    matches_to_check = set()
    if "potd" in state and isinstance(state["potd"], dict):
        m = state["potd"].get("match")
        if m:
            matches_to_check.add(m)

    for t in state.get("tickets", []):
        for p in t.get("picks", []):
            m = p.get("match")
            if m:
                matches_to_check.add(m)

    if not matches_to_check:
        print("Keine offenen Partien zu prüfen.")
        return

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }

    # Live- & Heutige Events abrufen
    try:
        res = requests.get("https://sportapi7.p.rapidapi.com/api/v1/sport/football/events/live", headers=headers, timeout=12)
        live_events = res.json().get("events", []) if res.status_code == 200 else []
    except Exception:
        live_events = []

    alerts = []

    for match_name in matches_to_check:
        # Match-ID aus den Events ermitteln
        matched_ev = None
        for ev in live_events:
            h = ev.get("homeTeam", {}).get("name", "").lower()
            a = ev.get("awayTeam", {}).get("name", "").lower()
            m_clean = match_name.lower()
            if (h in m_clean) or (a in m_clean):
                matched_ev = ev
                break

        if not matched_ev:
            continue

        event_id = matched_ev.get("id")
        if not event_id:
            continue

        # Lineup Endpunkt aufrufen
        try:
            lineup_res = requests.get(f"https://sportapi7.p.rapidapi.com/api/v1/event/{event_id}/lineups", headers=headers, timeout=10)
            if lineup_res.status_code != 200:
                continue

            lineup_data = lineup_res.json()
            home_lineup = lineup_data.get("home", {})
            away_lineup = lineup_data.get("away", {})

            if not home_lineup.get("players") or not away_lineup.get("players"):
                continue

            # Check auf Formation und Bestätigung
            h_form = home_lineup.get("formation", "N/A")
            a_form = away_lineup.get("formation", "N/A")
            h_name = matched_ev.get("homeTeam", {}).get("name")
            a_name = matched_ev.get("awayTeam", {}).get("name")

            alerts.append(
                f"📋 <b>Lineup bestätigt:</b> {h_name} ({h_form}) vs {a_name} ({a_form})\n"
                f"   ↳ <i>Start-Aufstellungen sind offiziell freigegeben.</i>"
            )
        except Exception as err:
            print(f"Fehler bei Lineup {event_id}: {err}")

    if alerts:
        msg = "⚡ <b>JARVIS LINEUP-RADAR</b>\n\n" + "\n\n".join(alerts)
        send_telegram_alert(msg)
        print("Lineup-Alerts gesendet.")
    else:
        print("Noch keine neuen Lineups verfügbar.")

if __name__ == "__main__":
    run_lineup_check()
