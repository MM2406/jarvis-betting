import os
import sys
import json
import re
import time
import csv
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from telegram_formatter import (
        send_to_sport_channel,
        edit_sport_channel_message,
        format_standalone_live_ticker,
        format_daily_settlement,
        shorten_tag
    )
except ImportError:
    send_to_sport_channel = None
    edit_sport_channel_message = None
    format_standalone_live_ticker = None
    format_daily_settlement = None
    def shorten_tag(t): return str(t)

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
HISTORY_CSV = "history_soccer.csv"
HISTORY_JSON = "soccer_history.json"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

def strip_kickoff_prefix(text):
    """Entfernt Anstoßzeit-Präfixe wie '[15:30 Uhr]' oder '[15:30]' vor dem Teamnamen."""
    if not text:
        return ""
    return re.sub(r"^\s*\[\s*\d{1,2}:\d{2}(?:\s*uhr)?\s*\]\s*", "", text, flags=re.IGNORECASE).strip()

def clean_team_name(name):
    clean = strip_kickoff_prefix(str(name)).lower()
    clean = re.sub(r"\b(bc|fc|cf|sc|ac|united|city|afc|ssc|rb|cp|calcio|ca|lisbon|lissabon|donetsk|u19|u21|u23|youth|frauen|women|tsg|1899|fk|sk)\b", " ", clean)
    clean = re.sub(r"[^\w\s]", " ", clean)
    return " ".join(clean.split()).strip()

def get_match_minute(ev):
    status = ev.get("status", {})
    desc = status.get("description", "").lower().strip()
    code = status.get("type", "").lower().strip()

    is_halftime = (
        code in ["halftime", "half_time", "ht"]
        or desc in ["halftime", "half time", "ht", "1st half ended", "first half ended"]
        or ("half" in desc and "2nd" not in desc and "second" not in desc and "ended" in desc)
    )
    if is_halftime:
        return 45, "Halbzeit", False

    is_finished = (
        code in ["finished", "ended", "ft", "after_ot", "after_pen"]
        or desc in ["ended", "finished", "ft", "aet", "pen", "full-time", "full time", "match finished"]
    )
    if is_finished:
        return 90, "Endstand", True

    minute = status.get("minute") or ev.get("time", {}).get("minute")
    if minute and isinstance(minute, (int, float)):
        m_int = int(minute)
        if m_int >= 90:
            extra = m_int - 90
            return 90, f"90+{extra}'" if extra > 0 else "90'", False
        return m_int, f"{m_int}'", False

    start_ts = ev.get("startTimestamp")
    if start_ts:
        now_ts = int(time.time())
        elapsed = (now_ts - start_ts) // 60
        if elapsed > 0:
            if "2nd" in desc or "second" in desc or elapsed > 60:
                calc_min = max(46, min(90, elapsed - 15))
                return calc_min, f"{calc_min}'", False
            else:
                calc_min = min(45, max(1, elapsed))
                return calc_min, f"{calc_min}'", False

    return 0, status.get("description", "Live"), False

def evaluate_pick_progress(match_str, pick_text, h_score, a_score, curr_min=0, is_finished=False):
    pt = pick_text.lower()
    total_goals = h_score + a_score

    # 1. Spieler-Props
    if any(k in pt for k in ["torschuss", "torschüsse", "shots on target", "scorer", "trifft", "torerzieler"]):
        if is_finished:
            return "✅ Spieler-Prop beendet", "🏁"
        return "⏳ Spieler aktiv", ("🟡" if curr_min >= 65 else "🟢")

    # 2. Über 2.5 Tore
    if "über 2.5" in pt or "over 2.5" in pt:
        if total_goals >= 3:
            return f"✅ {total_goals}/3 Tore", "🟢"
        if is_finished:
            return f"❌ {total_goals}/3 Tore", "🏁"
        if curr_min >= 70:
            return f"🔴 {total_goals}/3 Tore (Kritisch)", "🔴"
        if curr_min >= 45:
            return f"🟡 {total_goals}/3 Tore", "🟡"
        return f"⏳ {total_goals}/3 Tore", "🟢"

    # 3. Über 2.0 Tore
    if "über 2.0" in pt or "over 2.0" in pt:
        if total_goals > 2:
            return f"✅ {total_goals}/2 Tore", "🟢"
        if is_finished:
            return ("🟡 Push (2 Tore)", "🏁") if total_goals == 2 else (f"❌ {total_goals}/2 Tore", "🏁")
        if curr_min >= 70:
            return f"🔴 {total_goals}/2 Tore (Kritisch)", "🔴"
        return (f"🟡 {total_goals}/2 Tore", "🟡") if curr_min >= 45 else (f"⏳ {total_goals}/2 Tore", "🟢")

    # 4. Über 1.5 Tore
    if "über 1.5" in pt and "team" not in pt:
        if total_goals >= 2:
            return f"✅ {total_goals}/2 Tore", "🟢"
        if is_finished:
            return f"❌ {total_goals}/2 Tore", "🏁"
        if curr_min >= 75:
            return f"🔴 {total_goals}/2 Tore (Kritisch)", "🔴"
        return (f"🟡 {total_goals}/2 Tore", "🟡") if curr_min >= 55 else (f"⏳ {total_goals}/2 Tore", "🟢")

    # 5. Unter 2.5 Tore
    if "unter 2.5" in pt or "under 2.5" in pt:
        if total_goals >= 3:
            return f"❌ {total_goals} Tore (Max 2)", "🏁" if is_finished else "🔴"
        if is_finished:
            return f"✅ {total_goals} Tore (Max 2)", "🏁"
        if total_goals == 2:
            return f"🔴 {total_goals} Tore (Akut gefährdet)", "🔴"
        if curr_min >= 65:
            return f"🟡 {total_goals} Tore (Unter Druck)", "🟡"
        return f"⏳ {total_goals} Tore (Max 2)", "🟢"

    # 6. Beide treffen (BTTS)
    if "beide" in pt or "btts" in pt:
        hit = (1 if h_score > 0 else 0) + (1 if a_score > 0 else 0)
        if hit == 2:
            return "✅ Beide getroffen", "🟢"
        if is_finished:
            return f"❌ {hit}/2 Teams", "🏁"
        if curr_min >= 70:
            return f"🔴 {hit}/2 Teams (Kritisch)", "🔴"
        return (f"🟡 {hit}/2 Teams", "🟡") if curr_min >= 45 else (f"⏳ {hit}/2 Teams", "🟢")

    # 7. Siegwetten, DNB & Doppelte Chance
    clean_match = strip_kickoff_prefix(match_str)
    parts = [clean_team_name(p) for p in re.split(r"\s+vs\.?\s+|\s+-\s+", clean_match, flags=re.IGNORECASE)]
    if len(parts) >= 2:
        h_name, a_name = parts[0], parts[1]

        # Team-Tore
        if "team-tore" in pt or "team tore" in pt:
            team_score = h_score if h_name in pt else (a_score if a_name in pt else h_score)
            if team_score >= 2:
                return f"✅ {team_score}/2 Team-Tore", "🟢"
            if is_finished:
                return f"❌ {team_score}/2 Team-Tore", "🏁"
            if curr_min >= 70:
                return f"🔴 {team_score}/2 Team-Tore (Kritisch)", "🔴"
            return (f"🟡 {team_score}/2 Team-Tore", "🟡") if curr_min >= 45 else (f"⏳ {team_score}/2 Team-Tore", "🟢")

        is_home_pick = h_name in pt
        is_away_pick = a_name in pt

        # Doppelte Chance 1X
        if "1x" in pt:
            if h_score >= a_score:
                if is_finished:
                    return "✅ 1X gewonnen", "🏁"
                return ("🟡 1X knapp (Remis)", "🟡") if (h_score == a_score and curr_min >= 60) else ("🟢 1X auf Kurs", "🟢")
            if is_finished:
                return "❌ 1X verloren", "🏁"
            return "🔴 1X im Rückstand", "🔴"

        # DNB
        if "dnb" in pt:
            leads = (is_home_pick and h_score > a_score) or (is_away_pick and a_score > h_score)
            is_draw = (h_score == a_score)
            if leads:
                if is_finished:
                    return "✅ DNB gewonnen", "🏁"
                return "🟢 DNB Führung", "🟢"
            elif is_draw:
                if is_finished:
                    return "🟡 DNB Push (Void)", "🏁"
                return ("🟡 DNB (Remis)", "🟡") if curr_min >= 50 else ("⏳ DNB (Remis)", "🟢")
            else:
                if is_finished:
                    return "❌ DNB verloren", "🏁"
                return "🔴 DNB im Rückstand", "🔴"

        # Regulärer Sieg / Remis
        if "sieg" in pt or "remis" in pt:
            if "remis" in pt:
                if h_score == a_score:
                    return ("✅ Remis getroffen", "🏁") if is_finished else ("🟢 Remis", "🟢")
                return ("❌ Kein Remis", "🏁") if is_finished else (("🔴 Kein Remis", "🔴") if curr_min >= 70 else ("🟡 Kein Remis", "🟡"))

            leads = (is_home_pick and h_score > a_score) or (is_away_pick and a_score > h_score)
            is_draw = (h_score == a_score)

            if leads:
                if is_finished:
                    return "✅ Sieg gewonnen", "🏁"
                return ("🟢 Führung komfortabel", "🟢") if abs(h_score - a_score) >= 2 else ("🟡 Führung knapp", "🟡" if curr_min >= 65 else "🟢")
            elif is_draw:
                if is_finished:
                    return "❌ Kein Sieg (Remis)", "🏁"
                return ("🔴 Remis (Kritisch)", "🔴") if curr_min >= 70 else ("🟡 Remis", "🟡" if curr_min >= 40 else "🟢")
            else:
                if is_finished:
                    return "❌ Rückstand verloren", "🏁"
                return "🔴 Im Rückstand", "🔴"

    return None, "🟢"

def fallback_gemini_match(match_str):
    if not GEMINI_API_KEY:
        return None
    clean_match = strip_kickoff_prefix(match_str)
    print(f"[SoccerLive] Starte Gemini-Websuche Fallback für: {clean_match}...")
    prompt = f"Recherchiere via Google Search das aktuelle Zwischenergebnis oder Endergebnis für das Fußballspiel: {clean_match} von heute. Antworte exakt in zwei Zeilen:\nSTATUS: FINISHED oder LIVE oder UPCOMING\nSCORE: X:Y"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }
    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            ans = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            st = "UPCOMING"
            sc = "0:0"
            for line in ans.splitlines():
                if "STATUS:" in line: st = line.split("STATUS:")[1].strip().upper()
                if "SCORE:" in line: sc = line.split("SCORE:")[1].strip()
            if st in ["FINISHED", "LIVE"]:
                h_p, a_p = 0, 0
                if ":" in sc:
                    parts = sc.split(":")
                    h_p, a_p = int(re.sub(r"\D", "", parts[0]) or 0), int(re.sub(r"\D", "", parts[1]) or 0)
                return {"status": st, "h_score": h_p, "a_score": a_p, "min_label": "Endstand" if st == "FINISHED" else "Live"}
    except Exception as e:
        print(f"[SoccerLive] Fallback Gemini Fehler: {e}")
    return None

def append_to_history(records, json_settled_items=None):
    file_exists = os.path.exists(HISTORY_CSV)
    try:
        with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "Ticket", "Picks", "Odds", "Result", "Profit_Units"])
            for r in records:
                writer.writerow([
                    r.get("date", datetime.now().strftime("%Y-%m-%d")),
                    r.get("ticket", ""),
                    r.get("picks", ""),
                    r.get("odds", 1.0),
                    r.get("result", "FINISHED"),
                    r.get("profit", 0.0)
                ])
        print(f"[SoccerLive] {len(records)} Datensätze in {HISTORY_CSV} archiviert.")
    except Exception as e:
        print(f"[SoccerLive] Fehler beim Schreiben in {HISTORY_CSV}: {e}")

    if json_settled_items:
        history_list = []
        if os.path.exists(HISTORY_JSON):
            try:
                with open(HISTORY_JSON, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        history_list = content
                    elif isinstance(content, dict) and "settled" in content:
                        history_list = content["settled"]
            except Exception:
                history_list = []
        history_list.extend(json_settled_items)
        try:
            with open(HISTORY_JSON, "w", encoding="utf-8") as f:
                json.dump(history_list, f, ensure_ascii=False, indent=2)
            print(f"[SoccerLive] {len(json_settled_items)} Picks in {HISTORY_JSON} archiviert.")
        except Exception as e:
            print(f"[SoccerLive] Fehler beim Schreiben in {HISTORY_JSON}: {e}")

def send_telegram_msg(text, reply_to=None):
    if send_to_sport_channel:
        return send_to_sport_channel(text, sport="soccer", reply_to=reply_to)

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
        payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
    if reply_to:
        payload["reply_to_message_id"] = int(reply_to)

    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            return res.json().get("result", {}).get("message_id")
        print(f"[SoccerLive] Send Fehler: {res.text}")
    except Exception as e:
        print(f"[SoccerLive] Telegram Send Exception: {e}")
    return None

def edit_telegram(message_id, text):
    if edit_sport_channel_message:
        return edit_sport_channel_message(message_id, text)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not message_id:
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

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"[SoccerLive] Fehler beim Laden von {STATE_FILE}: {e}")
        return None

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SoccerLive] Fehler beim Speichern von {STATE_FILE}: {e}")

def fetch_football_events(date_str):
    if not RAPIDAPI_KEY:
        print("[SoccerLive] Kein RAPIDAPI_KEY hinterlegt.")
        return []
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }
    all_events = []
    
    try:
        url_live = "https://sportapi7.p.rapidapi.com/api/v1/sport/football/events/live"
        res = requests.get(url_live, headers=headers, timeout=12)
        if res.status_code == 200:
            events_live = res.json().get("events", [])
            all_events.extend(events_live)
            print(f"[SoccerLive] SportAPI Live-Events empfangen: {len(events_live)}")
        else:
            print(f"[SoccerLive] SportAPI Live-URL Status: {res.status_code}")
    except Exception as e:
        print(f"[SoccerLive] SportAPI Live Exception: {e}")

    dates_to_check = [date_str]
    try:
        prev_day = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_check.append(prev_day)
    except Exception:
        pass

    for d in dates_to_check:
        try:
            url_sched = f"https://sportapi7.p.rapidapi.com/api/v1/sport/football/scheduled-events/{d}"
            res_sched = requests.get(url_sched, headers=headers, timeout=12)
            if res_sched.status_code == 200:
                sched_events = res_sched.json().get("events", [])
                live_ids = {e.get("id") for e in all_events}
                for ev in sched_events:
                    if ev.get("id") not in live_ids:
                        all_events.append(ev)
                print(f"[SoccerLive] SportAPI Scheduled Events für {d}: {len(sched_events)}")
        except Exception as e:
            print(f"[SoccerLive] SportAPI Sched Exception für {d}: {e}")

    return all_events

def match_teams(search_str, home_name, away_name):
    full_event_str = f"{home_name} {away_name}".lower()
    if any(k in full_event_str for k in ["u19", "u21", "u23", "youth", "women", "frauen"]):
        return False

    h = clean_team_name(home_name)
    a = clean_team_name(away_name)
    clean_search = strip_kickoff_prefix(search_str)
    parts = [clean_team_name(p) for p in re.split(r"\s+vs\.?\s+|\s+-\s+", clean_search, flags=re.IGNORECASE) if clean_team_name(p)]
    
    if len(parts) >= 2:
        p1, p2 = parts[0], parts[1]
        if (p1 in h and p2 in a) or (p2 in h and p1 in a):
            return True

        p1_tokens = [w for w in p1.split() if len(w) >= 3]
        p2_tokens = [w for w in p2.split() if len(w) >= 3]

        if p1_tokens and p2_tokens:
            if any(t in h for t in p1_tokens) and any(t in a for t in p2_tokens):
                return True
            if any(t in h for t in p2_tokens) and any(t in a for t in p1_tokens):
                return True

    return False

def run_soccer_live():
    print(f"[{datetime.now(LOCAL_TZ).strftime('%H:%M:%S')}] Starte JARVIS Soccer Live Ticker...")
    state = load_state()
    if not state or not isinstance(state, dict) or not state.get("potd") and not state.get("tickets"):
        print("[SoccerLive] Keine aktiven Wetten in pending_soccer.json vorhanden. Beende geräuschlos.")
        return

    main_msg_id = state.get("message_id")
    ticker_msg_id = state.get("ticker_message_id")

    finished_matches = state.setdefault("finished_matches", {})
    match_picks = {}
    match_kickoffs = {}

    if "potd" in state and isinstance(state["potd"], dict):
        raw_m = state["potd"].get("match", "")
        p = state["potd"].get("pick")
        ko = state["potd"].get("kickoff", "")
        m = strip_kickoff_prefix(raw_m)
        if m:
            match_picks.setdefault(m, []).append(f"⭐ POTD: {p}")
            if ko:
                match_kickoffs[m] = ko

    raw_tickets = state.get("tickets", [])
    tickets_normalized = []
    
    if isinstance(raw_tickets, dict):
        for cat_name, legs in raw_tickets.items():
            if isinstance(legs, list):
                ticket_obj = {"ticket_name": cat_name.upper(), "picks": []}
                for l in legs:
                    if isinstance(l, dict):
                        ticket_obj["picks"].append(l)
                    elif isinstance(l, str):
                        ticket_obj["picks"].append({"match": l, "pick": ""})
                tickets_normalized.append(ticket_obj)
    elif isinstance(raw_tickets, list):
        tickets_normalized = raw_tickets

    for ticket in tickets_normalized:
        t_name = ticket.get("ticket_name", "Kombi")
        for p_item in ticket.get("picks", []):
            raw_m = p_item.get("match", "")
            p = p_item.get("pick", "")
            pl = p_item.get("player")
            ko = p_item.get("kickoff", "")
            m = strip_kickoff_prefix(raw_m)
            pick_label = f"{pl}: {p}" if pl else p
            if m:
                match_picks.setdefault(m, []).append(f"{t_name}: {pick_label}")
                if ko and m not in match_kickoffs:
                    match_kickoffs[m] = ko

    print(f"[SoccerLive] Überwache {len(match_picks)} Spiele (Haupt-Post: {main_msg_id}, Ticker-Post: {ticker_msg_id}).")

    today_str = state.get("date", datetime.now().strftime("%Y-%m-%d"))
    events = fetch_football_events(today_str)
    
    active_cards = []
    pending_list = []
    all_games_finished = True

    now_berlin = datetime.now(LOCAL_TZ)

    for match, picks in sorted(match_picks.items()):
        ko_str = f"[{match_kickoffs[match]}] " if match in match_kickoffs else ""

        if match in finished_matches:
            f_data = finished_matches[match]
            h_score = f_data["h_score"]
            a_score = f_data["a_score"]

            pick_evals = []
            for pick_desc in picks:
                eval_str, _ = evaluate_pick_progress(match, pick_desc, h_score, a_score, curr_min=90, is_finished=True)
                if eval_str:
                    tag = shorten_tag(pick_desc.split(":")[0])
                    pick_evals.append(f"  ↳ {eval_str} ({tag})")
            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""

            active_cards.append(
                f"🏁 <b>{match}</b> • <b>{h_score}:{a_score}</b> (<i>Endstand</i>){eval_block}"
            )
            continue

        matched_ev = None
        for ev in events:
            h = ev.get("homeTeam", {}).get("name", "")
            a = ev.get("awayTeam", {}).get("name", "")
            if match_teams(match, h, a):
                matched_ev = ev
                break

        if matched_ev:
            h_score = matched_ev.get("homeScore", {}).get("current", 0)
            a_score = matched_ev.get("awayScore", {}).get("current", 0)
            curr_min, min_label, is_finished = get_match_minute(matched_ev)
            status_desc = matched_ev.get("status", {}).get("description", "").lower()

            start_ts = matched_ev.get("startTimestamp")
            is_started_by_time = (start_ts and now_berlin.timestamp() >= start_ts)

            if status_desc in ["not started", "timed"] and curr_min == 0 and not is_started_by_time:
                all_games_finished = False
                pick_summaries = []
                for pick_desc in picks:
                    parts_p = pick_desc.split(":", 1)
                    tag = shorten_tag(parts_p[0])
                    p_text = parts_p[1].strip() if len(parts_p) > 1 else ""
                    pick_summaries.append(f"{p_text} ({tag})")
                p_joined = " • ".join(pick_summaries)
                pending_list.append(f"• <b>{ko_str}{match}</b> ➔ <i>{p_joined}</i>")
                continue

            if is_finished:
                finished_matches[match] = {
                    "h_score": h_score,
                    "a_score": a_score,
                    "finished_at": datetime.now(LOCAL_TZ).isoformat()
                }
                state["finished_matches"] = finished_matches
            else:
                all_games_finished = False

            if curr_min == 0 and is_started_by_time:
                elapsed = int((now_berlin.timestamp() - start_ts) // 60)
                curr_min = min(45, max(1, elapsed))
                min_label = f"{curr_min}'"

            # Dynamische Ampel-Ermittlung über alle Picks der Partie
            pick_evals = []
            worst_icon = "🟢"

            for pick_desc in picks:
                eval_str, p_icon = evaluate_pick_progress(match, pick_desc, h_score, a_score, curr_min=curr_min, is_finished=is_finished)
                if eval_str:
                    tag = shorten_tag(pick_desc.split(":")[0])
                    pick_evals.append(f"  ↳ {eval_str} ({tag})")
                    if p_icon == "🔴":
                        worst_icon = "🔴"
                    elif p_icon == "🟡" and worst_icon != "🔴":
                        worst_icon = "🟡"

            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""
            header_icon = "🏁" if is_finished else worst_icon

            active_cards.append(
                f"{header_icon} <b>{match}</b> • <b>{h_score}:{a_score}</b> (<i>{min_label}</i>){eval_block}"
            )
        else:
            gemini_res = fallback_gemini_match(match)
            if gemini_res and gemini_res["status"] in ["FINISHED", "LIVE"]:
                h_score = gemini_res["h_score"]
                a_score = gemini_res["a_score"]
                is_fin = gemini_res["status"] == "FINISHED"
                fallback_min = 90 if is_fin else 60

                if is_fin:
                    finished_matches[match] = {
                        "h_score": h_score,
                        "a_score": a_score,
                        "finished_at": datetime.now(LOCAL_TZ).isoformat()
                    }
                    state["finished_matches"] = finished_matches
                else:
                    all_games_finished = False

                pick_evals = []
                worst_icon = "🟢"

                for pick_desc in picks:
                    eval_str, p_icon = evaluate_pick_progress(match, pick_desc, h_score, a_score, curr_min=fallback_min, is_finished=is_fin)
                    if eval_str:
                        tag = shorten_tag(pick_desc.split(":")[0])
                        pick_evals.append(f"  ↳ {eval_str} ({tag})")
                        if p_icon == "🔴":
                            worst_icon = "🔴"
                        elif p_icon == "🟡" and worst_icon != "🔴":
                            worst_icon = "🟡"

                eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""
                header_icon = "🏁" if is_fin else worst_icon

                active_cards.append(
                    f"{header_icon} <b>{match}</b> • <b>{h_score}:{a_score}</b> (<i>{gemini_res['min_label']}</i>){eval_block}"
                )
            else:
                all_games_finished = False
                pick_summaries = []
                for pick_desc in picks:
                    parts_p = pick_desc.split(":", 1)
                    tag = shorten_tag(parts_p[0])
                    p_text = parts_p[1].strip() if len(parts_p) > 1 else ""
                    pick_summaries.append(f"{p_text} ({tag})")
                p_joined = " • ".join(pick_summaries)
                pending_list.append(f"• <b>{ko_str}{match}</b> ➔ <i>{p_joined}</i>")

    # Ticker formatieren
    if format_standalone_live_ticker:
        ticker_text = format_standalone_live_ticker("soccer", active_cards, pending_list)
    else:
        ticker_lines = ["⏱️ <b>JARVIS SOCCER • LIVE-TRACKER & FORTSCHRITT</b>\n"]
        if active_cards:
            ticker_lines.append("\n".join(active_cards))
        if pending_list:
            sep = "\n━━━━━━━━━━━━━━━━━━━━\n" if active_cards else ""
            ticker_lines.append(f"{sep}⏳ <b>AUSSTEHEND (Startet in Kürze)</b>\n" + "\n".join(pending_list))
        ticker_text = "\n".join(ticker_lines).strip()

    last_ticker_text = state.get("last_ticker_text", "")

    # Telegram senden oder editieren
    if not ticker_msg_id:
        print("[SoccerLive] Erstelle ersten eigenständigen Ticker-Post in Telegram...")
        new_id = send_telegram_msg(ticker_text, reply_to=main_msg_id)
        if new_id:
            state["ticker_message_id"] = new_id
            state["last_ticker_text"] = ticker_text
            save_state(state)
            print(f"[SoccerLive] ✅ Ticker-Post erfolgreich erstellt (ID: {new_id}).")
    else:
        if ticker_text != last_ticker_text:
            print(f"[SoccerLive] Editiere Ticker-Post (ID: {ticker_msg_id})...")
            if edit_telegram(ticker_msg_id, ticker_text):
                state["last_ticker_text"] = ticker_text
                save_state(state)
                print("[SoccerLive] ✅ Ticker-Post erfolgreich editiert.")
            else:
                print("[SoccerLive] ❌ Ticker-Edit fehlgeschlagen.")
        else:
            print("[SoccerLive] Ticker-Inhalt unverändert. Kein Edit nötig.")
            save_state(state)

    # Settlement bei Spielende aller Partien
    if all_games_finished and len(finished_matches) == len(match_picks) and not state.get("settled", False):
        print("[SoccerLive] Alle Spiele beendet! Starte Tagesabschluss und Settlement...")
        ticket_results = []
        history_records = []
        json_history_records = []
        tickets_won = 0
        tickets_lost = 0
        tickets_push = 0
        tickets_manual = 0
        total_profit = 0.0

        all_tickets_to_eval = []

        if "potd" in state and isinstance(state["potd"], dict):
            potd_odds = float(state["potd"].get("odds", 1.60))
            potd_stake = float(state["potd"].get("stake", 1.50))
            raw_potd_m = state["potd"].get("match", "")
            clean_potd_m = strip_kickoff_prefix(raw_potd_m)
            all_tickets_to_eval.append({
                "ticket_name": "⭐ SOCCER POTD",
                "odds": potd_odds,
                "stake": potd_stake,
                "picks": [{"match": clean_potd_m, "pick": state["potd"].get("pick")}]
            })

        for t in tickets_normalized:
            t_odds = float(t.get("odds", 2.0))
            stake = float(t.get("stake", 1.0))
            norm_picks = []
            for p in t.get("picks", []):
                p_copy = dict(p)
                p_copy["match"] = strip_kickoff_prefix(p_copy.get("match", ""))
                norm_picks.append(p_copy)
            all_tickets_to_eval.append({
                "ticket_name": t.get("ticket_name", "Kombi"),
                "odds": t_odds,
                "stake": stake,
                "picks": norm_picks
            })

        today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

        for t in all_tickets_to_eval:
            t_name = t["ticket_name"]
            t_odds = t["odds"]
            stake = t["stake"]
            picks = t["picks"]

            has_loss = False
            has_manual = False
            pick_summaries = []

            for p in picks:
                m_str = strip_kickoff_prefix(p.get("match", ""))
                p_str = p.get("pick", "")
                pl_str = p.get("player")
                p_label = f"{pl_str}: {p_str}" if pl_str else p_str
                f_data = finished_matches.get(m_str)

                if not f_data:
                    has_manual = True
                    pick_summaries.append(f"{m_str} (Offen)")
                    continue

                h_s = f_data["h_score"]
                a_s = f_data["a_score"]
                eval_res, _ = evaluate_pick_progress(m_str, p_label, h_s, a_s, curr_min=90, is_finished=True)

                if eval_res and "❌" in eval_res:
                    has_loss = True
                    pick_summaries.append(f"{m_str} ❌")
                elif eval_res and ("🟡" in eval_res or "push" in eval_res.lower() or "void" in eval_res.lower()):
                    pick_summaries.append(f"{m_str} 🟡")
                elif eval_res and "✅" in eval_res:
                    pick_summaries.append(f"{m_str} ✅")
                else:
                    has_manual = True
                    pick_summaries.append(f"{m_str} ❓")

            if has_loss:
                t_status = "❌ LOSS"
                profit = -stake
                tickets_lost += 1
                status_raw = "LOST"
            elif has_manual:
                t_status = "❓ MANUAL"
                profit = 0.0
                tickets_manual += 1
                status_raw = "PENDING"
            else:
                all_pushes = all("🟡" in ps for ps in pick_summaries)
                if all_pushes:
                    t_status = "🟡 PUSH"
                    profit = 0.0
                    tickets_push += 1
                    status_raw = "PUSH"
                else:
                    t_status = "✅ WIN"
                    profit = round(stake * (t_odds - 1.0), 2)
                    tickets_won += 1
                    status_raw = "WON"

            total_profit += profit

            sign = "+" if profit > 0 else ""
            profit_str = f"{sign}{profit:.2f}u" if profit != 0 else "0.0u"
            ticket_results.append(f"• <b>{shorten_tag(t_name)}</b> (@{t_odds:.2f}) ➔ {t_status} (<i>{profit_str}</i>)")

            history_records.append({
                "date": today_iso,
                "ticket": t_name,
                "picks": " // ".join(pick_summaries),
                "odds": t_odds,
                "result": status_raw,
                "profit": profit
            })

            json_history_records.append({
                "date": today_iso,
                "sport": "Soccer",
                "ticket": t_name,
                "picks": pick_summaries,
                "odds": t_odds,
                "stake": stake,
                "pnl": profit,
                "status": status_raw
            })

        append_to_history(history_records, json_settled_items=json_history_records)
        state["settled"] = True
        save_state(state)

        if format_daily_settlement:
            summary_msg = format_daily_settlement(
                sport="soccer",
                ticket_results=ticket_results,
                tickets_won=tickets_won,
                tickets_lost=tickets_lost,
                tickets_push=tickets_push,
                tickets_manual=tickets_manual,
                total_profit=total_profit,
                history_file_name="history_soccer.csv & soccer_history.json"
            )
        else:
            net_sign = "+" if total_profit > 0 else ""
            summary_msg = (
                f"🏁 <b>JARVIS SOCCER — TAGESABSCHLUSS</b>\n\n"
                f"<b>Ticket-Auswertung:</b>\n" + "\n".join(ticket_results) + f"\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Bilanz Tickets:</b> <b>{tickets_won}W - {tickets_lost}L</b>\n"
                f"💰 <b>Netto-Ergebnis:</b> <b>{net_sign}{total_profit:.2f} Units</b>"
            )

        send_telegram_msg(summary_msg, reply_to=ticker_msg_id or main_msg_id)
        print("[SoccerLive] ✅ Tagesabschluss mit Ticket-Abrechnung gesendet.")

if __name__ == "__main__":
    run_soccer_live()
