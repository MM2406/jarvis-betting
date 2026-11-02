import os
import sys
import json
import re
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Sichere Anbindung der zentralen Telegram-Hilfsfunktion
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_MONEYRACE", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

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

        if "message is not modified" in err_desc:
            return True

        payload.pop("parse_mode", None)
        res2 = requests.post(url, json=payload, timeout=25)
        if res2.status_code == 200 or "message is not modified" in res2.text:
            return True

        print(f"Telegram Edit fehlgeschlagen: {res.text}")
        return False
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

    now_berlin = datetime.now(LOCAL_TZ)
    print(f"Prüfe Live-Status für: {match_name} ({now_berlin.strftime('%H:%M Uhr')})...")

    # 1. Zeitschutz: Vor offizieller Beginnzeit niemals als LIVE einstufen
    match_time_match = re.search(r"(\d{1,2}):(\d{2})\s*Uhr", raw_text)
    if match_time_match:
        sched_hour = int(match_time_match.group(1))
        sched_min = int(match_time_match.group(2))
        try:
            match_dt = datetime.strptime(match_date, "%Y-%m-%d").replace(
                hour=sched_hour, minute=sched_min, tzinfo=LOCAL_TZ
            )
            if now_berlin < match_dt:
                print(f"Spiel beginnt erst um {sched_hour:02d}:{sched_min:02d} Uhr. Live-Suche übersprungen.")
                return
        except Exception:
            pass

    # 2. Status-Ermittlung über Gemini 3.8-Flash mit Google Search
    prompt = f"""
Du bist ein automatisierter Sport-Settlement- und Live-Tracker.
Recherchiere via Google Search den offiziellen Status für folgende Partie:
- Begegnung: {match_name}
- Datum: {match_date}
- Tipp: {pick_text}

REGELN:
1. STATUS:
   - 'FINISHED' (Spiel ist offiziell beendet, inkl. OT/Shootout)
   - 'LIVE' (Spiel läuft aktuell)
   - 'UPCOMING' (Spiel hat noch nicht begonnen)
2. SCORE: Aktueller Spielstand (z.B. '108:114' oder '2:1').
3. QUARTER_OR_TIME: Bei Basketball z.B. 'Q3' oder 'Ende Q4', bei Fussball '65. Min', bei Beendet 'FINAL'.
4. ASSESSMENT: 'ON_TRACK' (wenn Tipp gewinnt) oder 'AT_RISK'.
5. OUTCOME: Falls STATUS == 'FINISHED', bewerte '{pick_text}':
   - 'WON' (gewonnen)
   - 'LOST' (verloren)
   - 'VOID' (Push / Quote 1.0)
   - 'PENDING' (falls noch nicht beendet)

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder LIVE oder UPCOMING
SCORE: Spielstand
TIME_INFO: Zeitangabe oder FINAL
ASSESSMENT: ON_TRACK oder AT_RISK
OUTCOME: WON oder LOST oder VOID oder PENDING
"""

    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(api_url, json=payload, timeout=45)
        if res.status_code != 200:
            print(f"Gemini API Fehler: {res.status_code}")
            return

        ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"Gemini Antwort:\n{ans}")

        status = "UPCOMING"
        score = "-"
        time_info = ""
        track = "ON_TRACK"
        outcome = "PENDING"

        for line in ans.splitlines():
            line = line.strip()
            if line.startswith("STATUS:"):
                status = line.replace("STATUS:", "").strip().upper()
            elif line.startswith("SCORE:"):
                score = line.replace("SCORE:", "").strip()
            elif line.startswith("TIME_INFO:"):
                time_info = line.replace("TIME_INFO:", "").strip()
            elif line.startswith("ASSESSMENT:"):
                track = line.replace("ASSESSMENT:", "").strip().upper()
            elif line.startswith("OUTCOME:"):
                outcome = line.replace("OUTCOME:", "").strip().upper()

        if status == "UPCOMING":
            print("Spiel hat noch nicht begonnen.")
            return

        # 3. Live-Abschnitt im Ticket editieren
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
            edit_telegram(msg_id, new_text)
            active["original_text"] = new_text

        # 4. Automatisches Settlement bei Spielende
        if status == "FINISHED" and outcome in ["WON", "LOST", "VOID"]:
            step_num = int(active.get("step", 1))
            
            try:
                stake = float(str(active.get("stake", 5.0)).replace(",", "."))
            except ValueError:
                stake = 5.0
            try:
                odds_val = float(str(active.get("odds", 1.5)).replace(",", "."))
            except ValueError:
                odds_val = 1.5

            try:
                expected_return = float(str(active.get("expected_return", round(stake * odds_val, 2))).replace(",", "."))
            except ValueError:
                expected_return = round(stake * odds_val, 2)

            if outcome == "WON":
                state["bankroll"] = round(expected_return, 2)
                state["current_step"] = step_num
                
                history_entry = {
                    "step": step_num,
                    "match": match_name,
                    "pick": pick_text,
                    "odds": odds_val,
                    "stake": stake,
                    "return": round(expected_return, 2),
                    "status": "WON",
                    "date": active.get("date")
                }
                state.setdefault("history", []).append(history_entry)
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
                
                history_entry = {
                    "step": step_num,
                    "match": match_name,
                    "pick": pick_text,
                    "odds": odds_val,
                    "stake": stake,
                    "return": 0.0,
                    "status": "LOST",
                    "date": active.get("date")
                }
                state.setdefault("history", []).append(history_entry)
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
                    f"Einsatz von {stake:.2f} € erstattet. Stufe {step_num} wird wiederholt."
                )
                send_telegram_notification(void_msg)

        else:
            save_state(state)

    except Exception as e:
        print(f"Fehler im Live-Update / Settlement: {e}")

if __name__ == "__main__":
    run_live_update()
