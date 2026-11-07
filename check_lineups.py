import os
import json
import re
import requests
from datetime import datetime

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

PENDING_FILE = "pending_soccer.json"

def strip_kickoff_prefix(text):
    """Entfernt Anstoßzeit-Präfixe wie '[15:30 Uhr]' vor dem Teamnamen."""
    if not text:
        return ""
    return re.sub(r"^\s*\[\s*\d{1,2}:\d{2}(?:\s*uhr)?\s*\]\s*", "", text, flags=re.IGNORECASE).strip()

def clean_name(name):
    clean = strip_kickoff_prefix(str(name)).lower()
    clean = re.sub(r"\b(fc|cf|sc|ac|united|city|afc|ssc|rb|cp|calcio|ca|tsg|fk|sk|vfb|vfl|bvb)\b", " ", clean)
    clean = re.sub(r"[^\w\s]", " ", clean)
    return " ".join(clean.split()).strip()

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
        print("[LineupCheck] Keine pending_soccer.json gefunden.")
        return

    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"[LineupCheck] Fehler beim Laden von {PENDING_FILE}: {e}")
        return

    # Sammle nur Spiele, bei denen konkrete Spieler-Props vorliegen
    target_matches = {}
    
    # 1. POTD prüfen
    if "potd" in state and isinstance(state["potd"], dict):
        m = state["potd"].get("match")
        p = state["potd"].get("pick", "")
        pl = state["potd"].get("player", "")
        if m and (pl or any(k in p.lower() for k in ["torschuss", "torschüsse", "scorer", "trifft", "torerzieler"])):
            clean_m = strip_kickoff_prefix(m)
            target_matches.setdefault(clean_m, []).append({"player": pl, "pick": p, "raw_match": m})

    # 2. Tickets prüfen
    for t in state.get("tickets", []):
        for item in t.get("picks", []):
            m = item.get("match")
            p = item.get("pick", "")
            pl = item.get("player", "")
            if m and (pl or any(k in p.lower() for k in ["torschuss", "torschüsse", "scorer", "trifft", "torerzieler"])):
                clean_m = strip_kickoff_prefix(m)
                target_matches.setdefault(clean_m, []).append({"player": pl, "pick": p, "raw_match": m})

    if not target_matches:
        print("[LineupCheck] Keine Spieler-Props vorhanden. Kein Check nötig.")
        return

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }

    today_str = state.get("date", datetime.now().strftime("%Y-%m-%d"))
    events = []
    
    try:
        url_sched = f"https://sportapi7.p.rapidapi.com/api/v1/sport/football/scheduled-events/{today_str}"
        res = requests.get(url_sched, headers=headers, timeout=12)
        if res.status_code == 200:
            events.extend(res.json().get("events", []))
    except Exception as e:
        print(f"[LineupCheck] Fehler beim Abruf des Spielplans: {e}")

    # Fallback auf Live-Events, falls Spielplan leer ist
    if not events:
        try:
            res_live = requests.get("https://sportapi7.p.rapidapi.com/api/v1/sport/football/events/live", headers=headers, timeout=12)
            if res_live.status_code == 200:
                events.extend(res_live.json().get("events", []))
        except Exception:
            pass

    critical_alerts = []

    for match_name, prop_items in target_matches.items():
        matched_ev = None
        parts = [clean_name(p) for p in re.split(r"\s+vs\.?\s+|\s+-\s+", match_name, flags=re.IGNORECASE) if clean_name(p)]

        for ev in events:
            h = clean_name(ev.get("homeTeam", {}).get("name", ""))
            a = clean_name(ev.get("awayTeam", {}).get("name", ""))
            if len(parts) >= 2:
                p1, p2 = parts[0], parts[1]
                if (p1 in h and p2 in a) or (p2 in h and p1 in a):
                    matched_ev = ev
                    break

                # Token-Fallback
                p1_tokens = [w for w in p1.split() if len(w) >= 3]
                p2_tokens = [w for w in p2.split() if len(w) >= 3]
                if p1_tokens and p2_tokens:
                    if any(t in h for t in p1_tokens) and any(t in a for t in p2_tokens):
                        matched_ev = ev
                        break
                    if any(t in h for t in p2_tokens) and any(t in a for t in p1_tokens):
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

            # Starters (Startelf)
            h_starters = [p.get("player", {}).get("name", "").lower() for p in home_lineup.get("players", [])]
            a_starters = [p.get("player", {}).get("name", "").lower() for p in away_lineup.get("players", [])]
            all_starters = h_starters + a_starters

            if not all_starters:
                continue  # Aufstellung liegt für dieses Spiel noch nicht vor

            for item in prop_items:
                target_player = item["player"].lower() if item["player"] else ""
                pick_text = item["pick"].lower()
                search_term = target_player if target_player else pick_text

                # Prüfen, ob der Spieler in der Startelf steht
                is_starting = False
                for starter in all_starters:
                    tokens = [t for t in starter.split() if len(t) >= 4]
                    if any(t in search_term for t in tokens) or (target_player and target_player in starter):
                        is_starting = True
                        break

                display_match = item.get("raw_match", match_name)

                if is_starting:
                    print(f"[LineupCheck] OK: '{search_term}' steht in der Startelf bei {display_match}.")
                else:
                    player_display = item["player"] if item["player"] else item["pick"]
                    critical_alerts.append(
                        f"⚠️ <b>ROTATIONS-WARNUNG | {display_match}</b>\n"
                        f"Der Spieler <b>{player_display}</b> steht <u>NICHT</u> in der Startelf!\n"
                        f"<i>(Tipp: {item['pick']})</i>"
                    )

        except Exception as err:
            print(f"[LineupCheck] Fehler bei Event {event_id}: {err}")

    # Telegram wird nur benachrichtigt, wenn Gefahr für einen Tipp besteht
    if critical_alerts:
        msg = "🚨 <b>JARVIS LINEUP-ALARM</b>\n\n" + "\n\n".join(critical_alerts)
        send_telegram_alert(msg)
        print("[LineupCheck] Warnung über Telegram abgesetzt.")
    else:
        print("[LineupCheck] Check abgeschlossen. Alle getippten Prop-Spieler starten oder Lineups noch nicht online. Chat bleibt ruhig.")

if __name__ == "__main__":
    run_lineup_check()
