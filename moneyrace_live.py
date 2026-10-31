import os
import sys
import json
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", os.environ.get("TELEGRAM_THREAD_ID", "")).strip()

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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
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
        except:
            pass
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Fehler beim Senden der Telegram-Meldung: {e}")

def make_minute_bar(minute, total=90):
    clamped = max(0, min(minute, total))
    blocks = int((clamped / total) * 12)
    return f"[{'█' * blocks}{'░' * (12 - blocks)}]"

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
    now_berlin = datetime.now(LOCAL_TZ).strftime("%H:%M Uhr")

    print(f"Prüfe Live-Status für: {match_name} (Aktuelle Uhrzeit: {now_berlin})...")

    prompt = f"""
Du bist ein automatisierter Live-Sport-Tracker.
Recherchiere via Google Search den ECHTEN LIVE-SPIELSTAND für dieses Match:
- Begegnung: {match_name}
- Datum: {match_date}
- Wette: {pick_text}

SUCH-ANWEISUNG:
Suche nach "{match_name} live score", "{match_name} sofascore" oder "{match_name} flashscore".

ERMITTLE:
1. STATUS:
   - 'LIVE' (falls Spiel aktuell läuft oder Halbzeitpause ist)
   - 'FINISHED' (falls Spiel offiziell abgepfiffen wurde)
   - 'UPCOMING' (nur wenn noch nicht begonnen)
2. MINUTE: Aktuelle Spielminute (0 bis 90). Bei FINISHED 90.
3. SCORE: Exakter aktueller Spielstand (z.B. '0:2').
4. ASSESSMENT: 
   - 'ON_TRACK' (wenn der Tipp aktuell gewinnt)
   - 'AT_RISK' (wenn der Tipp aktuell verlieren würde)
5. OUTCOME: Falls STATUS == 'FINISHED', bewerte den Tipp '{pick_text}':
   - 'WON' (Tipp ist definitiv gewonnen)
   - 'LOST' (Tipp ist verloren)
   - 'PENDING' (falls noch nicht beendet)

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder LIVE oder UPCOMING
MINUTE: Zahl
SCORE: Spielstand
ASSESSMENT: ON_TRACK oder AT_RISK
OUTCOME: WON oder LOST oder PENDING
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        res = requests.post(url, json=payload, timeout=45)
        if res.status_code != 200:
            print(f"Gemini API Fehler: {res.status_code}")
            return

        ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"Gemini Antwort:\n{ans}")

        status = "UPCOMING"
        minute = 0
        score = "-"
        track = "ON_TRACK"
        outcome = "PENDING"

        for line in ans.split("\n"):
            line = line.strip()
            if line.startswith("STATUS:"):
                status = line.replace("STATUS:", "").strip().upper()
            elif line.startswith("MINUTE:"):
                try:
                    minute = int(re.search(r'\d+', line).group())
                except:
                    minute = 90 if status == "FINISHED" else 45
            elif line.startswith("SCORE:"):
                score = line.replace("SCORE:", "").strip()
            elif line.startswith("ASSESSMENT:"):
                track = line.replace("ASSESSMENT:", "").strip().upper()
            elif line.startswith("OUTCOME:"):
                outcome = line.replace("OUTCOME:", "").strip().upper()

        if status == "UPCOMING":
            print("Spiel hat noch nicht begonnen.")
            return

        # 1. Ticket in Telegram aktualisieren
        bar = make_minute_bar(minute)
        pct = int((min(minute, 90) / 90) * 100)
        track_icon = "🟢 Pick auf Kurs" if track == "ON_TRACK" else "🟡 Pick unter Druck"

        if status == "FINISHED":
            new_live_section = (
                f"⏱️ <b>LIVE-TRACKER • BEENDET</b>\n"
                f"[████████████] 100%\n"
                f"• <b>Endstand:</b> {score}\n"
                f"• <b>Status:</b> Spiel offiziell beendet"
            )
        else:
            minute_display = f"{minute}. Min"
            new_live_section = (
                f"⏱️ <b>LIVE-TRACKER • SPIEL LÄUFT</b>\n"
                f"{bar} {pct}% ({minute_display})\n"
                f"• <b>Spielstand:</b> <b>{score}</b>\n"
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

        # 2. Vollautomatisches Settlement bei Spielende
        if status == "FINISHED":
            print(f"Spiel beendet. Ergebnis der Wette: {outcome}")
            
            step_num = active.get("step", 3)
            stake = float(active.get("stake", 0))
            expected_return = float(active.get("expected_return", 0))

            if outcome == "WON":
                state["bankroll"] = round(expected_return, 2)
                state["current_step"] = step_num  # History enthält jetzt 1 bis step_num
                
                history_entry = {
                    "step": step_num,
                    "match": match_name,
                    "pick": pick_text,
                    "odds": active.get("odds"),
                    "stake": stake,
                    "return": round(expected_return, 2),
                    "status": "WON",
                    "date": active.get("date")
                }
                state.setdefault("history", []).append(history_entry)
                state["active_pick"] = None

                save_state(state)
                print("State erfolgreich auf WON aktualisiert!")

                # Erfolgsmeldung in Telegram
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
                    "odds": active.get("odds"),
                    "stake": stake,
                    "return": 0.0,
                    "status": "LOST",
                    "date": active.get("date")
                }
                state.setdefault("history", []).append(history_entry)
                state["active_pick"] = None

                save_state(state)
                print("State erfolgreich auf LOST aktualisiert!")

                lose_msg = (
                    f"❌ <b>MONEYRACE • STUFE {step_num} VERLOREN</b>\n\n"
                    f"📌 <b>Match:</b> {match_name}\n"
                    f"🎯 <b>Tipp:</b> {pick_text} (Endstand: {score})\n"
                    f"🔄 <b>Challenge-Reset:</b> Rückkehr zu Stufe 1 ({state['bankroll']:.2f} €)."
                )
                send_telegram_notification(lose_msg)

        else:
            save_state(state)

    except Exception as e:
        print(f"Fehler im Live-Update / Settlement: {e}")

if __name__ == "__main__":
    run_live_update()
