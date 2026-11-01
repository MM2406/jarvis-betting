import os
import sys
import json
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_NFL_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_NFL", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_nfl.json"
HISTORY_FILE = "nfl_history.json"

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_NFL_THREAD_ID")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine NFL Thread-ID vorhanden.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "message_thread_id": int(TELEGRAM_THREAD_ID)
    }

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=25)
            return res2.json().get("result", {}).get("message_id") if res2.status_code == 200 else None
        return res.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram-Fehler: {e}")
        return None

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else data.get("pending", [])
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

def append_to_history(settled_picks):
    if not settled_picks:
        return
    history = {"settled": [], "pending": []}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    history = content
                elif isinstance(content, list):
                    history = {"settled": content, "pending": []}
        except Exception as e:
            print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")

    history.setdefault("settled", []).extend(settled_picks)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"[History] {len(settled_picks)} Picks in {HISTORY_FILE} archiviert.")
    except Exception as e:
        print(f"Fehler beim Speichern in {HISTORY_FILE}: {e}")

def settle_nfl():
    pending = load_pending()
    if not pending:
        print("Keine offenen NFL-Picks zur Auswertung.")
        return

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes NFL-Spiel:
Match: {item.get('match')}
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob das Match regulär beendet ist. Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Push (z.B. Handicap genau getroffen) gib 'VOID' aus.
4. Gib eine kurze, präzise Begründung an.

Antworte exakt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: [Endergebnis]
INFO: [1-2 Sätze Begründung]
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                score_val = ""
                info_val = ""
                for line in text.splitlines():
                    if line.startswith("SCORE:"):
                        score_val = line.replace("SCORE:", "").strip()
                    elif line.startswith("INFO:"):
                        info_val = line.replace("INFO:", "").strip()

                item["score"] = score_val
                item["info"] = info_val

                if "RESULT: WON" in text:
                    item["status"] = "WON"
                    settled_now.append(item)
                elif "RESULT: LOST" in text:
                    item["status"] = "LOST"
                    settled_now.append(item)
                elif "RESULT: VOID" in text:
                    item["status"] = "VOID"
                    settled_now.append(item)
                else:
                    still_pending.append(item)
            else:
                still_pending.append(item)
        except Exception as e:
            print(f"Fehler bei NFL-Settle {item.get('match')}: {e}")
            still_pending.append(item)

    if settled_now:
        append_to_history(settled_now)
        save_pending(still_pending)

        total_tickets = len(settled_now)
        won_tickets = sum(1 for p in settled_now if p["status"] == "WON")
        void_tickets = sum(1 for p in settled_now if p["status"] == "VOID")

        total_staked = 0.0
        total_returned = 0.0

        today_display = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
        msg = f"🏈 <b>JARVIS NFL ABRECHNUNG</b>\n"
        msg += f"<i>Abrechnung der Spiele vom {today_display}</i>\n"

        for p in settled_now:
            try:
                odds_val = float(str(p.get("odds", "1.0")).replace(",", "."))
            except ValueError:
                odds_val = 1.0

            stake = float(p.get("stake", 1.0))
            total_staked += stake

            status = p["status"]
            if status == "WON":
                icon = "✅"
                ret = stake * odds_val
                profit_leg = ret - stake
                status_txt = f"✅ WON (+{profit_leg:.2f} U)"
                total_returned += ret
            elif status == "VOID":
                icon = "🟡"
                ret = stake
                status_txt = "🟡 PUSH/VOID (Quote 1.00)"
                total_returned += ret
            else:
                icon = "❌"
                status_txt = f"❌ LOST (-{stake:.2f} U)"

            msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"{icon} <b>{p['match']}</b>\n"
            msg += f"• <b>Tipp:</b> {p['pick']} (@ {odds_val:.2f})\n"
            if p.get("score"):
                msg += f"• <b>Ergebnis:</b> {p['score']}\n"
            if p.get("info"):
                msg += f"• <i>{p['info']}</i>\n"
            msg += f"• <b>Status:</b> {status_txt}\n"

        net_profit = total_returned - total_staked
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        valid_tickets = total_tickets - void_tickets
        hit_rate = (won_tickets / valid_tickets * 100) if valid_tickets > 0 else 0.0
        sign = "+" if net_profit >= 0 else ""

        msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
        msg += "📊 <b>PERFORMANCE DASHBOARD & METRIKEN</b>\n"
        msg += f"• <b>Ticket Win-Rate:</b> {won_tickets}/{total_tickets} ({hit_rate:.1f}%) {make_progress_bar(hit_rate)}\n"
        msg += f"• <b>Einsatz / Return:</b> {total_staked:.2f}U ➔ {total_returned:.2f}U\n"
        msg += f"• <b>Netto-Profit:</b>     <b>{sign}{net_profit:.2f} Units</b>\n"
        msg += f"• <b>Tages-ROI:</b>        <b>{sign}{roi:.1f}%</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━"

        send_telegram(msg)
    else:
        save_pending(still_pending)

if __name__ == "__main__":
    settle_nfl()
