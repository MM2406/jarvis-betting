import os
import sys
import json
import re
import time
import csv
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
HISTORY_FILE = "history_soccer.csv"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

def clean_team_name(name):
    clean = str(name).lower()
    clean = re.sub(r"\b(bc|fc|cf|sc|ac|united|city|afc|ssc|rb|cp|calcio|ca|lisbon|lissabon|donetsk|u19|u21|u23|youth|frauen|women|tsg|1899|fk|sk)\b", " ", clean)
    clean = re.sub(r"[^\w\s]", " ", clean)
    return " ".join(clean.split()).strip()

def shorten_tag(tag):
    tag_clean = str(tag).strip()
    mapping = {
        "CONSERVATIVE 2-LEG BANKER": "BANKER",
        "BALANCED VALUE ACCA": "BALANCED",
        "HYBRID QUANT MULTI": "HYBRID",
        "GOALS & BTTS VALUE ACCA": "GOALS",
        "PLAYER PROP SPOTLIGHT / MULTI-TICKET": "PROPS",
        "PLAYER PROPS MULTI": "PROPS",
        "⭐ POTD": "POTD",
        "POTD": "POTD",
        "BANKER": "BANKER",
        "BALANCED": "BALANCED",
        "GOALS": "GOALS",
        "HYBRID": "HYBRID",
        "PROPS": "PROPS"
    }
    return mapping.get(tag_clean, tag_clean)

def make_progress_bar(current, total=90, length=10):
    pct = min(1.0, max(0.0, current / total))
    filled = int(round(pct * length))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(pct * 100)}%"

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

def evaluate_pick_progress(match_str, pick_text, h_score, a_score, is_finished=False):
    pt = pick_text.lower()
    total_goals = h_score + a_score

    if any(k in pt for k in ["torschuss", "torschüsse", "shots on target", "scorer", "trifft", "torerzieler"]):
        if is_finished:
            return "✅ Spieler-Prop beendet"
        return "⏳ Spieler im Einsatz"

    if "über 2.5" in pt or "over 2.5" in pt:
        if total_goals >= 3:
            return f"✅ {total_goals}/3 Tore"
        return f"❌ {total_goals}/3 Tore" if is_finished else f"⏳ {total_goals}/3 Tore"

    if "über 2.0" in pt or "over 2.0" in pt:
        if total_goals > 2:
            return f"✅ {total_goals}/2 Tore"
        elif total_goals == 2 and is_finished:
            return "🟡 Push (2 Tore)"
        return f"❌ {total_goals}/2 Tore" if is_finished else f"⏳ {total_goals}/2 Tore"

    if "über 1.5" in pt and "team" not in pt:
        if total_goals >= 2:
            return f"✅ {total_goals}/2 Tore"
        return f"❌ {total_goals}/2 Tore" if is_finished else f"⏳ {total_goals}/2 Tore"

    if "unter 2.5" in pt or "under 2.5" in pt:
        if total_goals >= 3:
            return f"❌ {total_goals} Tore (Max 2)"
        return f"✅ {total_goals} Tore (Max 2)" if is_finished else f"⏳ {total_goals} Tore (Max 2)"

    if "beide" in pt or "btts" in pt:
        hit = (1 if h_score > 0 else 0) + (1 if a_score > 0 else 0)
        if hit == 2:
            return "✅ Beide getroffen"
        return f"❌ {hit}/2 Teams" if is_finished else f"⏳ {hit}/2 Teams"

    parts = [clean_team_name(p) for p in re.split(r"\s+vs\.?\s+|\s+-\s+", match_str, flags=re.IGNORECASE)]
    if len(parts) >= 2:
        h_name, a_name = parts[0], parts[1]

        if "team-tore" in pt or "team tore" in pt:
            team_score = h_score if h_name in pt else (a_score if a_name in pt else h_score)
            if team_score >= 2:
                return f"✅ {team_score}/2 Team-Tore"
            return f"❌ {team_score}/2 Team-Tore" if is_finished else f"⏳ {team_score}/2 Team-Tore"

        is_home_pick = h_name in pt
        is_away_pick = a_name in pt

        if "1x" in pt:
            if h_score >= a_score:
                return "✅ 1X auf Kurs" if not is_finished else "✅ 1X gewonnen"
            return "❌ 1X verloren" if is_finished else "⏳ 1X im Rückstand"

        if "dnb" in pt:
            if (is_home_pick and h_score > a_score) or (is_away_pick and a_score > h_score):
                return "✅ DNB auf Kurs" if not is_finished else "✅ DNB gewonnen"
            elif h_score == a_score:
                return "⏳ DNB (Remis)" if not is_finished else "🟡 DNB Push (Void)"
            return "❌ DNB verloren" if is_finished else "⏳ DNB im Rückstand"

        if "sieg" in pt or "remis" in pt:
            if "remis" in pt:
                if h_score == a_score:
                    return "⏳ Remis" if not is_finished else "✅ Remis getroffen"
                return "❌ Kein Remis" if is_finished else "⏳ Kein Remis"
            if (is_home_pick and h_score > a_score) or (is_away_pick and a_score > h_score):
                return "✅ Führung" if not is_finished else "✅ Sieg gewonnen"
            elif h_score == a_score:
                return "⏳ Remis" if not is_finished else "❌ Kein Sieg"
            return "❌ Rückstand" if is_finished else "⏳ Rückstand"

    return None

def fallback_gemini_match(match_str):
    if not GEMINI_API_KEY:
        return None
    print(f"[SoccerLive] Starte Gemini-Websuche Fallback für: {match_str}...")
    prompt = f"Recherchiere via Google Search das aktuelle Zwischenergebnis oder Endergebnis für das Fußballspiel: {match_str} von heute. Antworte exakt in zwei Zeilen:\nSTATUS: FINISHED oder LIVE oder UPCOMING\nSCORE: X:Y"
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

def append_to_history(records):
    file_exists = os.path.exists(HISTORY_FILE)
    try:
        with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
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
    except Exception as e:
        print(f"[SoccerLive] Fehler beim Schreiben in {HISTORY_FILE}: {e}")

def send_telegram_msg(text):
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
        print(f"[SoccerLive] Telegram Send Fehler: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[SoccerLive] Fehler beim Laden von {STATE_FILE}: {e}")
        return None

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SoccerLive] Fehler beim Speichern von {STATE_FILE}: {e}")

def edit_telegram(message_id, text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not message_id:
        print("[SoccerLive] Telegram Credentials oder message_id fehlen für Edit.")
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
        print(f"[SoccerLive] Edit mit HTML fehlgeschlagen ({res.text}), versuche ohne parse_mode...")
        payload.pop("parse_mode", None)
        res2 = requests.post(url, json=payload, timeout=20)
        return res2.status_code == 200 or "message is not modified" in res2.text
    except Exception as e:
        print(f"[SoccerLive] Telegram Edit Ausnahme: {e}")
        return False

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
    parts = [clean_team_name(p) for p in re.split(r"\s+vs\.?\s+|\s+-\s+", search_str, flags=re.IGNORECASE) if clean_team_name(p)]
    
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
    if not state:
        print("[SoccerLive] Keine pending_soccer.json vorhanden. Beende.")
        return

    msg_id = state.get("message_id")
    raw_text = state.get("original_text", "")
    if not msg_id or not raw_text:
        print(f"[SoccerLive] Message-ID ({msg_id}) oder original_text fehlt. Beende.")
        return

    finished_matches = state.setdefault("finished_matches", {})
    match_picks = {}

    if "potd" in state and isinstance(state["potd"], dict):
        m = state["potd"].get("match")
        p = state["potd"].get("pick")
        if m:
            match_picks.setdefault(m, []).append(f"⭐ POTD: {p}")

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
            m = p_item.get("match")
            p = p_item.get("pick", "")
            pl = p_item.get("player")
            pick_label = f"{pl}: {p}" if pl else p
            if m:
                match_picks.setdefault(m, []).append(f"{t_name}: {pick_label}")

    print(f"[SoccerLive] Überwache insgesamt {len(match_picks)} Spiele mit Message-ID {msg_id}.")

    today_str = state.get("date", datetime.now().strftime("%Y-%m-%d"))
    events = fetch_football_events(today_str)
    
    active_cards = []
    pending_list = []
    all_games_finished = True

    for match, picks in sorted(match_picks.items()):
        if match in finished_matches:
            f_data = finished_matches[match]
            h_score = f_data["h_score"]
            a_score = f_data["a_score"]
            progress_bar = make_progress_bar(90, total=90, length=10)

            pick_evals = []
            for pick_desc in picks:
                eval_str = evaluate_pick_progress(match, pick_desc, h_score, a_score, is_finished=True)
                if eval_str:
                    tag = shorten_tag(pick_desc.split(":")[0])
                    pick_evals.append(f"   ↳ {eval_str} ({tag})")
            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""

            active_cards.append(
                f"🏁 <b>{match}</b> | <b>{h_score}:{a_score}</b> (Endstand)\n"
                f"   Zeit: <code>{progress_bar}</code>"
                f"{eval_block}"
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

            if status_desc in ["not started", "timed"] and curr_min == 0:
                all_games_finished = False
                pick_summaries = []
                for pick_desc in picks:
                    parts_p = pick_desc.split(":", 1)
                    tag = shorten_tag(parts_p[0])
                    p_text = parts_p[1].strip() if len(parts_p) > 1 else ""
                    pick_summaries.append(f"{p_text} ({tag})")
                p_joined = " • ".join(pick_summaries)
                pending_list.append(f"• <b>{match}</b> ➔ <i>{p_joined}</i>")
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

            progress_bar = make_progress_bar(curr_min, total=90, length=10)
            pick_evals = []
            for pick_desc in picks:
                eval_str = evaluate_pick_progress(match, pick_desc, h_score, a_score, is_finished=is_finished)
                if eval_str:
                    tag = shorten_tag(pick_desc.split(":")[0])
                    pick_evals.append(f"   ↳ {eval_str} ({tag})")

            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""
            icon = "🏁" if is_finished else "🟢"

            active_cards.append(
                f"{icon} <b>{match}</b> | <b>{h_score}:{a_score}</b> ({min_label})\n"
                f"   Zeit: <code>{progress_bar}</code>"
                f"{eval_block}"
            )
        else:
            gemini_res = fallback_gemini_match(match)
            if gemini_res and gemini_res["status"] in ["FINISHED", "LIVE"]:
                h_score = gemini_res["h_score"]
                a_score = gemini_res["a_score"]
                is_fin = gemini_res["status"] == "FINISHED"
                if is_fin:
                    finished_matches[match] = {
                        "h_score": h_score,
                        "a_score": a_score,
                        "finished_at": datetime.now(LOCAL_TZ).isoformat()
                    }
                    state["finished_matches"] = finished_matches
                else:
                    all_games_finished = False

                progress_bar = make_progress_bar(90 if is_fin else 45, total=90, length=10)
                pick_evals = []
                for pick_desc in picks:
                    eval_str = evaluate_pick_progress(match, pick_desc, h_score, a_score, is_finished=is_fin)
                    if eval_str:
                        tag = shorten_tag(pick_desc.split(":")[0])
                        pick_evals.append(f"   ↳ {eval_str} ({tag})")
                eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""
                icon = "🏁" if is_fin else "🟢"
                active_cards.append(
                    f"{icon} <b>{match}</b> | <b>{h_score}:{a_score}</b> ({gemini_res['min_label']})\n"
                    f"   Zeit: <code>{progress_bar}</code>"
                    f"{eval_block}"
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
                pending_list.append(f"• <b>{match}</b> ➔ <i>{p_joined}</i>")

    live_sections = ["⏱️ <b>LIVE-TRACKER & FORTSCHRITT</b>"]
    if active_cards:
        live_sections.append("\n\n".join(active_cards))
    if pending_list:
        if active_cards:
            live_sections.append("━━━━━━━━━━━━━━━━━━━━\n⏳ <b>AUSSTEHEND (Startet in Kürze)</b>\n" + "\n".join(pending_list))
        else:
            live_sections.append("⏳ <b>AUSSTEHEND (Startet in Kürze)</b>\n" + "\n".join(pending_list))

    live_block = "\n\n".join(live_sections)

    split_targets = ["⏱️ <b>LIVE-TRACKER", "⏱️ <b>LIVE-", "⏳ <b>AUSSTEHEND"]
    base_text = raw_text
    for target in split_targets:
        if target in base_text:
            base_text = base_text.split(target)[0].rstrip()

    if base_text.endswith("━━━━━━━━━━━━━━━━━━━━"):
        new_text = base_text + "\n" + live_block
    else:
        new_text = base_text + "\n\n━━━━━━━━━━━━━━━━━━━━\n" + live_block

    if new_text.strip() != raw_text.strip():
        print(f"[SoccerLive] Neuer Ticker-Inhalt erkannt! Sende Update an Telegram (ID: {msg_id})...")
        if edit_telegram(msg_id, new_text):
            state["original_text"] = new_text
            save_state(state)
            print("[SoccerLive] ✅ Telegram Nachricht erfolgreich editiert.")
        else:
            print("[SoccerLive] ❌ Telegram Edit fehlgeschlagen.")
    else:
        print("[SoccerLive] Keine sichtbare Änderung am Ticker-Text. Telegram-Nachricht bleibt unverändert.")
        save_state(state)

    # Settlement
    if all_games_finished and len(finished_matches) == len(match_picks) and not state.get("settled", False):
        print("[SoccerLive] Alle Spiele beendet! Starte Tagesabschluss und Settlement...")
        ticket_results = []
        history_records = []
        tickets_won = 0
        tickets_lost = 0
        tickets_push = 0
        tickets_manual = 0
        total_profit = 0.0

        all_tickets_to_eval = []

        if "potd" in state and isinstance(state["potd"], dict):
            potd_odds = float(state["potd"].get("odds", 1.60))
            all_tickets_to_eval.append({
                "ticket_name": "⭐ SOCCER POTD",
                "odds": potd_odds,
                "stake": 1.5,
                "picks": [{"match": state["potd"].get("match"), "pick": state["potd"].get("pick")}]
            })

        for t in tickets_normalized:
            t_odds = float(t.get("odds", 2.0))
            stake = 1.0
            t_name_upper = t.get("ticket_name", "").upper()
            if "BANKER" in t_name_upper:
                stake = 1.25
            elif "VALUE" in t_name_upper:
                stake = 0.75
            elif "HYBRID" in t_name_upper or "PROPS" in t_name_upper:
                stake = 0.5

            all_tickets_to_eval.append({
                "ticket_name": t.get("ticket_name", "Kombi"),
                "odds": t_odds,
                "stake": stake,
                "picks": t.get("picks", [])
            })

        for t in all_tickets_to_eval:
            t_name = t["ticket_name"]
            t_odds = t["odds"]
            stake = t["stake"]
            picks = t["picks"]

            has_loss = False
            has_manual = False
            pick_summaries = []

            for p in picks:
                m_str = p.get("match", "")
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
                eval_res = evaluate_pick_progress(m_str, p_label, h_s, a_s, is_finished=True) or ""

                if "❌" in eval_res:
                    has_loss = True
                    pick_summaries.append(f"{m_str} ❌")
                elif "🟡" in eval_res or "push" in eval_res.lower() or "void" in eval_res.lower():
                    pick_summaries.append(f"{m_str} 🟡")
                elif "✅" in eval_res:
                    pick_summaries.append(f"{m_str} ✅")
                else:
                    has_manual = True
                    pick_summaries.append(f"{m_str} ❓")

            if has_loss:
                t_status = "❌ LOSS"
                profit = -stake
                tickets_lost += 1
            elif has_manual:
                t_status = "❓ MANUAL"
                profit = 0.0
                tickets_manual += 1
            else:
                all_pushes = all("🟡" in ps for ps in pick_summaries)
                if all_pushes:
                    t_status = "🟡 PUSH"
                    profit = 0.0
                    tickets_push += 1
                else:
                    t_status = "✅ WIN"
                    profit = round(stake * (t_odds - 1.0), 2)
                    tickets_won += 1

            total_profit += profit

            sign = "+" if profit > 0 else ""
            profit_str = f"{sign}{profit:.2f}u" if profit != 0 else "0.0u"
            ticket_results.append(f"• <b>{shorten_tag(t_name)}</b> (@{t_odds:.2f}) ➔ {t_status} (<i>{profit_str}</i>)")

            history_records.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "ticket": t_name,
                "picks": " // ".join(pick_summaries),
                "odds": t_odds,
                "result": t_status.replace("✅ ", "").replace("❌ ", "").replace("🟡 ", "").replace("❓ ", ""),
                "profit": profit
            })

        append_to_history(history_records)
        state["settled"] = True
        save_state(state)

        net_sign = "+" if total_profit > 0 else ""
        tickets_summary = "\n".join(ticket_results)

        summary_msg = (
            f"🏁 <b>JARVIS SOCCER — TAGESABSCHLUSS</b>\n\n"
            f"<b>Ticket-Auswertung (Kombis & POTD):</b>\n"
            f"{tickets_summary}\n\n"
            f"📊 <b>Bilanz Tickets:</b> <b>{tickets_won}W - {tickets_lost}L</b>"
            f"{f' - {tickets_push}P' if tickets_push > 0 else ''}"
            f"{f' ({tickets_manual} offen/Props)' if tickets_manual > 0 else ''}\n"
            f"💰 <b>Netto-Ergebnis:</b> <b>{net_sign}{total_profit:.2f} Units</b>\n\n"
            f"📁 <i>Alle Tickets wurden in history_soccer.csv archiviert.</i>"
        )
        send_telegram_msg(summary_msg)
        print("[SoccerLive] ✅ Tagesabschluss mit Ticket-Abrechnung gesendet.")

if __name__ == "__main__":
    run_soccer_live()
