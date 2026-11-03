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

    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return

    match_picks = {}
    if "potd" in state and isinstance(state["potd"], dict):
        m = state["potd"].get("match")
        p = state["potd"].get("pick")
        if m and p:
            match_picks.setdefault(m, []).append(p)

    for t in state.get("tickets", []):
        for item in t.get("picks", []):
            m = item.get("match")
            p = item.get("pick")
            if m and p:
                match_picks.setdefault(m, []).append(p)

    if not match_picks:
        print("Keine offenen Partien zu prüfen.")
        return

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }

    try:
        res = requests.get("https://sportapi7.p.rapidapi.com/api/v1/sport/football/events/live", headers=headers, timeout=12)
        live_events = res.json().get("events", []) if res.status_code == 200 else []
    except Exception:
        live_events = []

    alerts = []

    for match_name, picks in match_picks.items():
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

        try:
            lineup_res = requests.get(f"https://sportapi7.p.rapidapi.com/api/v1/event/{event_id}/lineups", headers=headers, timeout=10)
            if lineup_res.status_code != 200:
                continue

            lineup_data = lineup_res.json()
            home_lineup = lineup_data.get("home", {})
            away_lineup = lineup_data.get("away", {})

            h_players = [p.get("player", {}).get("name", "").lower() for p in home_lineup.get("players", [])]
            a_players = [p.get("player", {}).get("name", "").lower() for p in away_lineup.get("players", [])]
            all_starters = h_players + a_players

            h_name = matched_ev.get("homeTeam", {}).get("name")
            a_name = matched_ev.get("awayTeam", {}).get("name")

            # Prüfung auf Player-Props in den Picks
            player_alerts = []
            for pick in picks:
                p_lower = pick.lower()
                if any(k in p_lower for k in ["torschuss", "torschüsse", "scorer", "trifft", "torerzieler"]):
                    found = False
                    for starter in all_starters:
                        # Nachname oder Vorname enthalten
                        name_parts = starter.split()
                        if any(len(part) > 3 and part in p_lower for part in name_parts):
                            found = True
                            player_alerts.append(f"🟢 <i>Stammplatz bestätigt:</i> <b>{starter.title()}</b> startet in der Startelf.")
                            break
                    if not found and all_starters:
                        player_alerts.append(f"⚠️ <b>Achtung Rotations-Gefahr:</b> Spieler aus Tipp '<i>{pick}</i>' steht evtl. nicht in der offiziellen Startelf!")

            alerts.append(
                f"📋 <b>{h_name} vs {a_name}</b> (Lineups bestätigt)\n" +
                ("\n".join(player_alerts) if player_alerts else "   ↳ <i>Formationen & Kader bestätigt.</i>")
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
