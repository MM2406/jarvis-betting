import os
import sys
import json
import re
import time
import csv
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

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
HISTORY_FILE = "history_soccer.csv"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

def clean_team_name(name):
    clean = re.sub(r"\b(bc|fc|cf|sc|ac|united|city|afc|ssc|rb|calcio|ca)\b", "", name.lower())
    return clean.strip()

def make_progress_bar(current, total=90, length=10):
    pct = min(1.0, max(0.0, current / total))
    filled = int(round(pct * length))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(pct * 100)}%"

def get_match_minute(ev):
    status = ev.get("status", {})
    desc = status.get("description", "").lower()
    code = status.get("type", "").lower()

    if any(k in desc for k in ["ended", "finished", "ft", "aet", "pen"]) or code in ["finished", "ended"]:
        return 90, "Endstand", True

    if "halftime" in desc or "half time" in desc or "ht" in desc:
        return 45, "Halbzeit", False

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
        if "2nd" in desc or "second" in desc:
            calc_min = max(46, elapsed - 15)
            if calc_min >= 90:
                extra = calc_min - 90
                return 90, f"90+{extra}'" if extra > 0 else "90'", False
            return calc_min, f"{calc_min}'", False
        else:
            calc_min = min(45, max(1, elapsed))
            return calc_min, f"{calc_min}'", False

    return 0, status.get("description", "Live"), False

def evaluate_pick_progress(match_str, pick_text, h_score, a_score, is_finished=False):
    pt = pick_text.lower()
    total_goals = h_score + a_score

    # 1. Spieler-Props (Torschüsse / Tore / Scorer)
    if any(k in pt for k in ["torschuss", "torschüsse", "shots on target", "scorer", "trifft", "torerzieler"]):
        if is_finished:
            return "✅ Spieler-Prop beendet (Stats erfasst)"
        return "⏳ Spieler im Einsatz"

    # 2. Tore-Märkte
    if "über 2.5" in pt or "over 2.5" in pt:
        if total_goals >= 3:
            return f"✅ {total_goals}/3 Tore"
        return f"❌ {total_goals}/3 Tore" if is_finished else f"⏳ {total_goals}/3 Tore"

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

    # 3. Team-Tore
    if "team-tore" in pt or "team tore" in pt:
        m_parts = [clean_team_name(p) for p in re.split(r"vs\.?| - ", match_str, flags=re.IGNORECASE)]
        if len(m_parts) >= 2:
            team_score = h_score if m_parts[0] in pt else (a_score if m_parts[1] in pt else h_score)
            if team_score >= 2:
                return f"✅ {team_score}/2 Team-Tore"
            return f"❌ {team_score}/2 Team-Tore" if is_finished else f"⏳ {team_score}/2 Team-Tore"

    # 4. Sieg- und 1X/DNB-Märkte
    m_parts = [clean_team_name(p) for p in re.split(r"vs\.?| - ", match_str, flags=re.IGNORECASE)]
    if len(m_parts) >= 2:
        h_name, a_name = m_parts[0], m_parts[1]
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
                return "⏳ DNB (Unentschieden)" if not is_finished else "🟡 DNB Push (Void)"
            return "❌ DNB verloren" if is_finished else "⏳ DNB im Rückstand"

        if "sieg" in pt:
            if (is_home_pick and h_score > a_score) or (is_away_pick and a_score > h_score):
                return "✅ Führung" if not is_finished else "✅ Sieg gewonnen"
            elif h_score == a_score:
                return "⏳ Remis" if not is_finished else "❌ Kein Sieg"
            return "❌ Rückstand" if is_finished else "⏳ Rückstand"

    return None

def append_to_history(records):
    file_exists = os.path.exists(HISTORY_FILE)
    try:
        with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "Match", "Pick", "Score", "Result", "Profit_Units"])
            for r in records:
                writer.writerow([
                    r.get("date", datetime.now().strftime("%Y-%m-%d")),
                    r.get("match", ""),
                    r.get("pick", ""),
                    r.get("score", ""),
                    r.get("result", "FINISHED"),
                    r.get("profit", 0.0)
                ])
    except Exception as e:
        print(f"Fehler beim Schreiben in {HISTORY_FILE}: {e}")

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
        print(f"Telegram-Fehler: {e}")

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
            print(f"[SportAPI HTTP {res.status_code}] Kontingent erreicht oder Fehler.")
    except Exception as e:
        print(f"[SportAPI Live Exception] {e}")
    return []

def match_teams(search_str, home_name, away_name):
    h = home_name.lower()
    a = away_name.lower()
    parts = [clean_team_name(p) for p in re.split(r"vs\.?| - ", search_str, flags=re.IGNORECASE) if clean_team_name(p)]
    if len(parts) >= 2:
        return (parts[0] in h and parts[1] in a) or (parts[1] in h and parts[0] in a)
    elif len(parts) == 1:
        return parts[0] in h or parts[0] in a
    return False

def run_soccer_live():
    state = load_state()
    if not state:
        print("[SoccerLive] Keine pending_soccer.json vorhanden.")
        return

    msg_id = state.get("message_id")
    raw_text = state.get("original_text", "")
    if not msg_id or not raw_text:
        return

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
        return

    live_events = fetch_live_football_events()
    live_status_lines = []
    all_games_finished = True

    for match, picks in sorted(match_picks.items()):
        # 1. Bereits final beendetes Spiel
        if match in finished_matches:
            f_data = finished_matches[match]
            h_score = f_data["h_score"]
            a_score = f_data["a_score"]
            progress_bar = make_progress_bar(90, total=90, length=10)

            pick_evals = []
            for pick_desc in picks:
                eval_str = evaluate_pick_progress(match, pick_desc, h_score, a_score, is_finished=True)
                if eval_str:
                    tag = pick_desc.split(":")[0]
                    pick_evals.append(f"   ↳ {eval_str} ({tag})")
            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""

            live_status_lines.append(
                f"🏁 <b>{match}</b> | <b>{h_score}:{a_score}</b> (Endstand)\n"
                f"   Zeit: <code>{progress_bar}</code>"
                f"{eval_block}"
            )
            continue

        # 2. In aktiven Live-Events suchen
        matched_ev = None
        for ev in live_events:
            h = ev.get("homeTeam", {}).get("name", "")
            a = ev.get("awayTeam", {}).get("name", "")
            if match_teams(match, h, a):
                matched_ev = ev
                break

        if matched_ev:
            h_score = matched_ev.get("homeScore", {}).get("current", 0)
            a_score = matched_ev.get("awayScore", {}).get("current", 0)
            curr_min, min_label, is_finished = get_match_minute(matched_ev)

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
                    tag = pick_desc.split(":")[0]
                    pick_evals.append(f"   ↳ {eval_str} ({tag})")

            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""
            icon = "🏁" if is_finished else "🔴"

            live_status_lines.append(
                f"{icon} <b>{match}</b> | <b>{h_score}:{a_score}</b> ({min_label})\n"
                f"   Zeit: <code>{progress_bar}</code>"
                f"{eval_block}"
            )
        else:
            # 3. Spiel noch nicht angepfiffen
            all_games_finished = False
            pick_evals = []
            for pick_desc in picks:
                eval_str = evaluate_pick_progress(match, pick_desc, 0, 0, is_finished=False)
                if eval_str:
                    tag = pick_desc.split(":")[0]
                    pick_evals.append(f"   ↳ {eval_str} ({tag})")
            eval_block = "\n" + "\n".join(pick_evals) if pick_evals else ""

            live_status_lines.append(
                f"⏳ <b>{match}</b> | <b>Wartet auf Anpfiff / Live-Score</b>\n"
                f"   Zeit: <code>[░░░░░░░░░░] 0%</code>"
                f"{eval_block}"
            )

    if not live_status_lines:
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
            print("[SoccerLive] Telegram erfolgreich aktualisiert.")
    else:
        save_state(state)

    # Automatische Abrechnung & Archivierung, wenn alle Spiele den Endstand erreicht haben
    if all_games_finished and len(finished_matches) == len(match_picks) and not state.get("settled", False):
        records = []
        wins = 0
        losses = 0
        for match, f_data in finished_matches.items():
            h_s = f_data["h_score"]
            a_s = f_data["a_score"]
            for pick_desc in match_picks.get(match, []):
                eval_res = evaluate_pick_progress(match, pick_desc, h_s, a_s, is_finished=True)
                is_win = "✅" in eval_res if eval_res else False
                if is_win:
                    wins += 1
                else:
                    losses += 1
                records.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "match": match,
                    "pick": pick_desc,
                    "score": f"{h_s}:{a_s}",
                    "result": "WIN" if is_win else "LOSS",
                    "profit": 0.85 if is_win else -1.0
                })
        
        append_to_history(records)
        state["settled"] = True
        save_state(state)

        summary_msg = (
            f"🏁 <b>JARVIS SOCCER — TAGESABSCHLUSS</b>\n\n"
            f"Alle Spiele des Abends sind beendet!\n"
            f"• Bilanz Picks: <b>{wins}W - {losses}L</b>\n\n"
            f"📁 <i>Ergebnisse wurden automatisch in history_soccer.csv archiviert.</i>"
        )
        send_telegram_msg(summary_msg)
        print("[SoccerLive] Tagesabschluss archiviert und Telegram-Zusammenfassung gesendet.")

if __name__ == "__main__":
    run_soccer_live()
