import os
import sys
import json
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_MONEYRACE", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

STATE_FILE = "moneyrace_state.json"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

SPORT_ENDPOINT_MAP = {
    "soccer": "football",
    "fussball": "football",
    "football": "football",
    "nba": "basketball",
    "basketball": "basketball",
    "euro-hoops": "basketball",
    "nhl": "ice-hockey",
    "ice-hockey": "ice-hockey",
    "eishockey": "ice-hockey",
    "tennis": "tennis",
    "nfl": "american-football",
    "american-football": "american-football"
}

def clean_team_name(name):
    """Entfernt Club-Kürzel für zuverlässigen API-Abgleich."""
    clean = re.sub(r"\b(bc|fc|cf|sc|ac|united|city|afc|ssc|rb|calcio|u19|u21|u23|youth|frauen|women)\b", "", name.lower())
    return " ".join(clean.split()).strip()

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
        if res.status_code == 200 or "message is not modified" in res.text:
            return True

        payload.pop("parse_mode", None)
        res2 = requests.post(url, json=payload, timeout=25)
        return res2.status_code == 200 or "message is not modified" in res2.text
    except Exception as e:
        print(f"Telegram Edit Ausnahme: {e}")
        return False

def send_telegram_notification(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_MONEYRACE_THREAD_ID")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except Exception:
            pass
    try:
        res = requests.post(url, json=payload, timeout=20)
        return res.json().get("result", {}).get("message_id") if res.status_code == 200 else None
    except Exception as e:
        print(f"Fehler beim Senden der Telegram-Meldung: {e}")
        return None

def detect_sport(active_pick):
    raw_sport = active_pick.get("sport", "").strip().lower()
    combined_text = f"{raw_sport} {active_pick.get('match', '')} {active_pick.get('pick', '')} {active_pick.get('original_text', '')}".lower()
    
    if any(k in combined_text for k in ["nba", "basketball", "euroleague", "hoops"]):
        return "basketball"
    if any(k in combined_text for k in ["nhl", "eishockey", "ice hockey"]):
        return "ice-hockey"
    if any(k in combined_text for k in ["nfl", "american football"]):
        return "american-football"
    if any(k in combined_text for k in ["tennis", "atp", "wta"]):
        return "tennis"
    return "soccer"

def fetch_rapidapi_sportapi(match_name, sport_name="soccer"):
    if not RAPIDAPI_KEY:
        return None

    sport_slug = SPORT_ENDPOINT_MAP.get(str(sport_name).strip().lower(), "football")
    url = f"https://sportapi7.p.rapidapi.com/api/v1/sport/{sport_slug}/events/live"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }

    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code != 200:
            print(f"[SportAPI Error HTTP {res.status_code}] {res.text}")
            return None

        events = res.json().get("events", [])
        raw_parts = [clean_team_name(p) for p in re.split(r"\s+vs\.?\s+|\s+-\s+|\s+@\s+", match_name, flags=re.IGNORECASE) if clean_team_name(p)]
        
        if len(raw_parts) < 2:
            return None

        p1, p2 = raw_parts[0], raw_parts[1]

        for ev in events:
            h_name = clean_team_name(ev.get("homeTeam", {}).get("name", ""))
            a_name = clean_team_name(ev.get("awayTeam", {}).get("name", ""))

            # Ausschluss von Jugendmannschaften
            full_check = f"{h_name} {a_name}"
            if any(k in full_check for k in ["u19", "u21", "youth"]):
                continue

            # STRIKT: BEIDE Teams müssen matchen (p1 vs p2)
            matched = (p1 in h_name and p2 in a_name) or (p2 in h_name and p1 in a_name)

            if matched:
                h_score = ev.get("homeScore", {}).get("current", 0)
                a_score = ev.get("awayScore", {}).get("current", 0)

                # Plausibilitätscheck: Fußball kann nicht 32:27 sein!
                if sport_slug == "football" and (h_score + a_score > 15):
                    print(f"⚠️ Unplausibler Fußball-Spielstand ({h_score}:{a_score}) ignoriert!")
                    continue

                score_str = f"{h_score}:{a_score}"
                
                status_raw = ev.get("status", {}).get("description", "").lower()
                status_code = ev.get("status", {}).get("type", "").lower()

                time_str = "Live"
                minute = ev.get("status", {}).get("minute") or ev.get("time", {}).get("minute")
                if minute:
                    time_str = f"{minute}'"
                elif "halftime" in status_raw or "ht" in status_raw:
                    time_str = "Halbzeit"
                elif "1st" in status_raw:
                    time_str = "1. HZ"
                elif "2nd" in status_raw:
                    time_str = "2. HZ"

                if any(k in status_raw for k in ["finished", "ended", "ft"]) or status_code in ["finished", "ended"]:
                    return {"status": "FINISHED", "score": score_str, "time_info": "FINAL", "h": h_score, "a": a_score}

                return {
                    "status": "LIVE",
                    "score": score_str,
                    "time_info": time_str,
                    "h": h_score,
                    "a": a_score
                }
    except Exception as e:
        print(f"[SportAPI Exception] {e}")

    return None

def fetch_gemini_search(match_name, match_date, pick_text, sport_name="soccer"):
    if not GEMINI_API_KEY:
        return None

    prompt = f"""
Du bist ein automatisierter Sport-Settlement- und Live-Tracker.
Recherchiere via Google Search den offiziellen Status für folgende Partie:
- Sportart: {sport_name}
- Begegnung: {match_name}
- Datum: {match_date}
- Tipp: {pick_text}

REGELN:
1. STATUS: 'FINISHED', 'LIVE' oder 'UPCOMING'
2. SCORE: Spielstand (z.B. '2:0')
3. TIME_INFO: z.B. '72. Min', 'Halbzeit' oder 'FINAL'
4. ASSESSMENT: 'ON_TRACK' (wenn Tipp gewinnt/führt) oder 'AT_RISK'
5. OUTCOME: Falls FINISHED: 'WON', 'LOST', 'VOID'. Sonst 'PENDING'.

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder LIVE oder UPCOMING
SCORE: Spielstand
TIME_INFO: Zeitangabe
ASSESSMENT: ON_TRACK oder AT_RISK
OUTCOME: WON oder LOST oder VOID oder PENDING
"""
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(api_url, json=payload, timeout=40)
        if res.status_code != 200:
            return None

        ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        parsed = {"status": "UPCOMING", "score": "-", "time_info": "", "track": "ON_TRACK", "outcome": "PENDING"}
        for line in ans.splitlines():
            line = line.strip()
            if line.startswith("STATUS:"):
                parsed["status"] = line.replace("STATUS:", "").strip().upper()
            elif line.startswith("SCORE:"):
                parsed["score"] = line.replace("SCORE:", "").strip()
            elif line.startswith("TIME_INFO:"):
                parsed["time_info"] = line.replace("TIME_INFO:", "").strip()
            elif line.startswith("ASSESSMENT:"):
                parsed["track"] = line.replace("ASSESSMENT:", "").strip().upper()
            elif line.startswith("OUTCOME:"):
                parsed["outcome"] = line.replace("OUTCOME:", "").strip().upper()
        return parsed
    except Exception as e:
        print(f"Gemini Fallback Fehler: {e}")
        return None

def run_live_update():
    state = load_state()
    if not state or not state.get("active_pick"):
        print("Kein aktiver Pick für Live-Tracking vorhanden.")
        return

    active = state["active_pick"]
    msg_id = active.get("message_id")
    raw_text = active.get("original_text", "")
    if not msg_id or not raw_text:
        return

    match_name = active.get("match", "")
    match_date = active.get("date", "")
    pick_text = active.get("pick", "")
    sport = detect_sport(active)

    # 1. Direkte Abfrage der SportAPI
    api_data = fetch_rapidapi_sportapi(match_name, sport_name=sport)
    
    status = "UPCOMING"
    score = "-"
    time_info = ""
    track = "ON_TRACK"
    outcome = "PENDING"

    if api_data:
        status = api_data["status"]
        score = api_data["score"]
        time_info = api_data["time_info"]
        h, a = api_data["h"], api_data["a"]

        if "sieg" in pick_text.lower():
            p_clean = clean_team_name(pick_text)
            parts = [clean_team_name(p) for p in re.split(r"vs\.?| - ", match_name, flags=re.IGNORECASE)]
            if len(parts) >= 2:
                if parts[0] in p_clean:
                    track = "ON_TRACK" if h > a else "AT_RISK"
                elif parts[1] in p_clean:
                    track = "ON_TRACK" if a > h else "AT_RISK"

        if status == "FINISHED":
            g_data = fetch_gemini_search(match_name, match_date, pick_text, sport_name=sport)
            outcome = g_data.get("outcome", "PENDING") if g_data else "PENDING"
    else:
        # Fallback auf Google Search nur wenn API nichts findet
        g_data = fetch_gemini_search(match_name, match_date, pick_text, sport_name=sport)
        if g_data:
            status = g_data["status"]
            score = g_data["score"]
            time_info = g_data["time_info"]
            track = g_data["track"]
            outcome = g_data["outcome"]

    # Wenn Spiel noch ansteht (vor Anpfiff): Ticker auf Wartezustand setzen oder beenden
    if status == "UPCOMING":
        print(f"[Moneyrace] {match_name} ist laut API noch nicht gestartet.")
        # Entferne eventuell fälschlich gesetzte "SPIEL LÄUFT"-Abschnitte
        pattern = r"⏱️ <b>LIVE-TRACKER.*?(\n━━━━━━━━━━━━━━━━━━━━|\Z)"
        if "LIVE-TRACKER • SPIEL LÄUFT" in raw_text:
            cleaned_text = re.sub(pattern, "", raw_text, flags=re.DOTALL).rstrip()
            if edit_telegram(msg_id, cleaned_text):
                active["original_text"] = cleaned_text
                save_state(state)
        return

    # 2. Live-Abschnitt in Telegram editieren
    track_icon = "🟢 Pick auf Kurs" if track == "ON_TRACK" else "🟡 Pick unter Druck"

    if status == "FINISHED":
        new_live_section = (
            f"⏱️ <b>LIVE-TRACKER • BEENDET</b>\n"
            f"[████████████] 100%\n"
            f"• <b>Endstand:</b> {score}\n"
            f"• <b>Status:</b> Spiel offiziell beendet"
        )
    else:
        time_display = f" ({time_info})" if time_info else ""
        new_live_section = (
            f"⏱️ <b>LIVE-TRACKER • SPIEL LÄUFT</b>\n"
            f"• <b>Spielstand:</b> <b>{score}</b>{time_display}\n"
            f"• <b>Trend:</b> {track_icon}"
        )

    pattern = r"⏱️ <b>LIVE-TRACKER.*?(\n━━━━━━━━━━━━━━━━━━━━|\Z)"
    if re.search(pattern, raw_text, flags=re.DOTALL):
        new_text = re.sub(pattern, f"{new_live_section}\\1", raw_text, count=1, flags=re.DOTALL)
    else:
        new_text = raw_text.rstrip() + "\n\n━━━━━━━━━━━━━━━━━━━━\n" + new_live_section

    if new_text.strip() != raw_text.strip():
        if edit_telegram(msg_id, new_text):
            active["original_text"] = new_text
            save_state(state)
            print("[Moneyrace] Telegram erfolgreich live aktualisiert!")

    # 3. Settlement bei Spielende
    if status == "FINISHED" and outcome in ["WON", "LOST", "VOID"]:
        step_num = int(active.get("step", 1))
        stake = float(str(active.get("stake", 5.0)).replace(",", "."))
        odds_val = float(str(active.get("odds", 1.5)).replace(",", "."))
        expected_return = float(str(active.get("expected_return", round(stake * odds_val, 2))).replace(",", "."))

        if outcome == "WON":
            state["bankroll"] = round(expected_return, 2)
            state["current_step"] = step_num
            state.setdefault("history", []).append({
                "step": step_num, "match": match_name, "pick": pick_text,
                "odds": odds_val, "stake": stake, "return": round(expected_return, 2),
                "status": "WON", "date": active.get("date")
            })
            state["active_pick"] = None
            save_state(state)

            win_msg = (
                f"✅ <b>MONEYRACE • STUFE {step_num} GEWONNEN!</b>\n\n"
                f"📌 <b>Match:</b> {match_name}\n"
                f"🎯 <b>Tipp:</b> {pick_text} (Endstand: {score})\n"
                f"💰 <b>Gewinn:</b> <b>{expected_return:.2f} €</b>\n\n"
                f"🚀 <b>Stufe {step_num + 1} freigeschaltet!</b>\n"
                f"Neue Bankroll: <b>{expected_return:.2f} €</b> (All-In)"
            )
            send_telegram_notification(win_msg)

        elif outcome == "LOST":
            state["bankroll"] = float(state.get("start_amount", 5.0))
            state["current_step"] = 0
            state.setdefault("history", []).append({
                "step": step_num, "match": match_name, "pick": pick_text,
                "odds": odds_val, "stake": stake, "return": 0.0,
                "status": "LOST", "date": active.get("date")
            })
            state["active_pick"] = None
            save_state(state)

            lose_msg = (
                f"❌ <b>MONEYRACE • STUFE {step_num} VERLOREN</b>\n\n"
                f"📌 <b>Match:</b> {match_name}\n"
                f"🎯 <b>Tipp:</b> {pick_text} (Endstand: {score})\n"
                f"🔄 <b>Challenge-Reset:</b> Rückkehr zu Stufe 1 ({state['bankroll']:.2f} €)."
            )
            send_telegram_notification(lose_msg)

        elif outcome == "VOID":
            state["active_pick"] = None
            save_state(state)
            void_msg = (
                f"🟡 <b>MONEYRACE • STUFE {step_num} VOID / PUSH</b>\n\n"
                f"📌 <b>Match:</b> {match_name}\n"
                f"🎯 <b>Tipp:</b> {pick_text} (Endstand: {score})\n"
                f"Einsatz erstattet. Stufe {step_num} wird wiederholt."
            )
            send_telegram_notification(void_msg)

if __name__ == "__main__":
    run_live_update()
