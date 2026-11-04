import os
import sys
import json
import time
import re
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Zentrale Telegram-Hilfsfunktion einbinden
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sichere Fallback-Kette für das Tennis-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_TENNIS_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_TENNIS", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "tennis_history.json"

TENNIS_SPORTS = [
    "tennis_atp",
    "tennis_wta"
]

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_TENNIS_THREAD_ID")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine Tennis Thread-ID vorhanden. Senden in den Hauptchat blockiert.")
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

def deduplicate_picks(items):
    seen = set()
    unique = []
    for item in items:
        key = (
            str(item.get("date", "")).strip().lower(),
            str(item.get("match", "")).strip().lower(),
            str(item.get("pick", "")).strip().lower()
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

def clean_score_text(raw_score):
    if not raw_score:
        return ""
    cleaned = re.sub(r"\s*\([^)]*\)", "", raw_score).strip()
    return cleaned

def clean_info_sentence(info):
    if not info:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", info.strip())
    return sentences[0] if sentences else info.strip()

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"settled": [], "pending": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("settled", [])
                data.setdefault("pending", [])
                data["pending"] = deduplicate_picks(data["pending"])
                return data
            elif isinstance(data, list):
                return {"settled": data, "pending": []}
    except Exception as e:
        print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")
    return {"settled": [], "pending": []}

def save_history(history):
    try:
        if isinstance(history, dict) and "pending" in history:
            history["pending"] = deduplicate_picks(history["pending"])
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

def settle_pending_picks(history):
    pending = history.get("pending", [])
    if not pending:
        print("Keine offenen Tennis-Picks zur Auswertung.")
        return history

    pending = deduplicate_picks(pending)
    still_pending = []
    settled_now = []

    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    for item in pending:
        match = item.get("match", "")
        pick = item.get("pick", "")
        date_str = item.get("date", "")
        is_kombi = item.get("is_kombi", False) or "+" in pick

        prompt_settle = f"""
Du bist 'JARVIS TENNIS SETTLEMENT AGENT'.
Recherchiere via Google Search das offizielle Endergebnis des folgenden ATP/WTA-Tennis-Matches:
Match: {match}
Tipp: {pick}
Datum: {date_str}
Ist Kombi: {is_kombi}

REGELN FÜR TENNIS:
1. Prüfe, ob das Match beendet ist (FINAL). Falls noch live, durch Regen verzögert oder noch nicht gestartet -> PENDING.
2. Wenn ein Spieler aufgibt (Retirement/Walkover): Falls der Buchmacher-Tipp dadurch ungültig wird oder unvollständig ist -> VOID (Push).
3. Bei Kombiwetten: Wenn alle Beine gewonnen sind -> WON, sobald ein Bein verloren ist -> LOST.
4. Bei regulärem Sieg nach Sätzen: Bewerte nach Match-Gewinn, Games-Handicap oder Over/Under Total Games.
5. Gib nur EINEN kurzen, prägnanten Satz Begründung an (max. 15 Wörter).

Antworte exakt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: [Satz-Ergebnis, z.B. 6:4, 3:6, 7:6]
INFO: [Maximal 1 kurzer Satz Begründung]
"""
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(api_url, json=payload, timeout=60)
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                score_val = ""
                info_val = ""
                result_val = "PENDING"
                for line in text.splitlines():
                    if line.startswith("SCORE:"):
                        score_val = line.replace("SCORE:", "").strip()
                    elif line.startswith("INFO:"):
                        info_val = line.replace("INFO:", "").strip()
                    elif line.startswith("RESULT:"):
                        result_val = line.replace("RESULT:", "").strip().upper()

                item["score"] = score_val
                item["info"] = info_val

                if result_val in ["WON", "LOST", "VOID"]:
                    item["status"] = result_val
                    item["sport"] = "Tennis"

                    try:
                        odds_val = float(str(item.get("odds", "1.0")).replace(",", "."))
                    except ValueError:
                        odds_val = 1.0
                    try:
                        stake_val = float(str(item.get("stake", "1.0")).replace(",", "."))
                    except ValueError:
                        stake_val = 1.0

                    item["stake"] = stake_val
                    item["odds"] = odds_val

                    if result_val == "WON":
                        item["pnl"] = round((odds_val - 1.0) * stake_val, 2)
                    elif result_val == "LOST":
                        item["pnl"] = round(-stake_val, 2)
                    else:
                        item["pnl"] = 0.0

                    settled_now.append(item)
                else:
                    still_pending.append(item)
            else:
                still_pending.append(item)
        except Exception as e:
            print(f"Fehler bei Tennis-Settle {match}: {e}")
            still_pending.append(item)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        total_tickets = len(settled_now)
        won_tickets = sum(1 for p in settled_now if p["status"] == "WON")
        void_tickets = sum(1 for p in settled_now if p["status"] == "VOID")

        total_staked = 0.0
        total_returned = 0.0

        today_display = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
        msg = f"🎾 <b>JARVIS TENNIS ABRECHNUNG</b>\n"
        msg += f"<i>Abrechnung der Matches vom {today_display}</i>\n"

        for p in settled_now:
            odds_val = float(p.get("odds", 1.0))
            stake = float(p.get("stake", 1.0))
            total_staked += stake

            status = p["status"]
            if status == "WON":
                icon = "✅"
                ret = stake * odds_val
                profit_leg = ret - stake
                outcome_str = f"<b>WON (+{profit_leg:.2f}u)</b>"
                total_returned += ret
            elif status == "VOID":
                icon = "🟡"
                ret = stake
                outcome_str = "<b>PUSH / RETIREMENT (0.0u)</b>"
                total_returned += ret
            else:
                icon = "❌"
                outcome_str = f"<b>LOST (-{stake:.2f}u)</b>"

            clean_score = clean_score_text(p.get("score", ""))
            score_display = f" | <b>{clean_score}</b>" if clean_score else ""

            msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"{icon} <b>{p['match']}</b>{score_display}\n"
            msg += f"   ↳ <i>{p['pick']}</i> (@{odds_val:.2f}) ➔ {icon} {outcome_str}\n"

            clean_info = clean_info_sentence(p.get("info", ""))
            if clean_info:
                msg += f"   • {clean_info}\n"

        net_profit = total_returned - total_staked
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        valid_tickets = total_tickets - void_tickets
        hit_rate = (won_tickets / valid_tickets * 100) if valid_tickets > 0 else 0.0
        sign = "+" if net_profit >= 0 else ""

        msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
        msg += "📊 <b>PERFORMANCE METRIKEN</b>\n"
        msg += f"• <b>Bilanz:</b>       <b>{won_tickets}W - {total_tickets - won_tickets - void_tickets}L</b>"
        if void_tickets > 0:
            msg += f" - <b>{void_tickets}P</b>"
        msg += f" ({hit_rate:.1f}%) {make_progress_bar(hit_rate)}\n"
        msg += f"• <b>Umsatz:</b>       {total_staked:.2f}u ➔ {total_returned:.2f}u\n"
        msg += f"• <b>Netto-Profit:</b> <b>{sign}{net_profit:.2f} Units</b>\n"
        msg += f"• <b>Tages-ROI:</b>    <b>{sign}{roi:.1f}%</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━"

        send_telegram(msg)

    return history

def fetch_tennis_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=14)

    for sport in TENNIS_SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                for match in res.json():
                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue
                        odds_details = []
                        for m in bookies[0].get("markets", []):
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_details.append(f"{m.get('key')}: {', '.join(outcomes)}")
                        league = "ATP" if "atp" in sport else "WTA"
                        all_events.append(f"[{league}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(odds_details)}")
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Tennis-Partien: {len(all_events)}")
    return "\n".join(all_events[:40])

def run_tennis_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    slate_name = "Tages-Slate (Europa / Asien)" if now_hour < 15 else "Abend- & Nacht-Slate (Übersee)"

    odds_data = fetch_tennis_odds()
    if not odds_data:
        print("Keine Tennis-Partien im aktuellen Zeitfenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS TENNIS QUANT' – Spezialist für ATP & WTA Matchup-Modellierung, Hold/Break-Prozentsätze und Belag-Diskrepanzen.
Erstelle für die aktuelle Slate ({today_str} – {slate_name}) das Tennis-Value-Dossier.

VERFÜGBARE MATCHES & QUOTEN:
{odds_data}

RICHTLINIEN & MÄRKTE:
- Wähle ausschließlich Matches aus der Liste.
- Analysiere Serve/Return Dominance Ratio, Belag-Profil (Hardcourt/Clay/Grass/Indoor), 1st Serve In % und Breakball-Verwertung via Google Search.
- Erstelle:
  1x Pick of the Day (1.5u)
  1x Value Acca (2-er Kombi mit Spreads/ML, 0.75u)
  1x Totals / Set-Handicap Spotlight (0.75u).
- Mindestquote beachten: Keine Quoten unter 1.35!

FORMATIERUNGS-REGELN FÜR TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzählung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Trennlinien exakt: '━━━━━━━━━━━━━━━━━━━━'
- Am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🎾 <b>JARVIS TENNIS INTEL DOSSIER</b>
<i>ATP & WTA Analytics • Surface Edge • Hold/Break Models</i>
<b>Slate:</b> {slate_name}

━━━━━━━━━━━━━━━━━━━━
⭐ <b>TENNIS PICK OF THE DAY (Single Bet)</b>
- <b>Match:</b> [Uhrzeit] Uhr | [ATP/WTA] [Spieler A] vs. [Spieler B]
➔ <b>Haupt-Pick:</b> <b>[Sieg / Games-Handicap / Satz-Wette]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 1.5 Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [Aufschlag-Dominanz, Hold-Statistiken, Return-Qualität, Formkurve]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA (2-er Kombi)</b>
- [Uhrzeit] Uhr | [Spieler A] vs. [Spieler B] ➔ <b>[Tipp 1]</b> @ [Quote]
- [Uhrzeit] Uhr | [Spieler C] vs. [Spieler D] ➔ <b>[Tipp 2]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> 0.75 Units
🔍 <b>Kombi-Logik:</b> [Warum diese Kombination rechnerischen Vorteil bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>TOTAL GAMES & SETS SPOTLIGHT</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Spieler A] vs. [Spieler B]
➔ <b>Pick:</b> <b>[Over/Under Games / Satz-Handicap]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 0.75 Units
🔍 <b>Rationale:</b> [Tie-Break-Wahrscheinlichkeit, Aufschlagstärke, historische H2H-Länge]

---JSON_TRACKING---
[
  {{
    "match": "Player A vs Player B",
    "sport": "Tennis",
    "category": "POTD",
    "pick": "Player A Sieg",
    "odds": 1.75,
    "stake": 1.5,
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "Player A vs Player B // Player C vs Player D",
    "sport": "Tennis",
    "category": "ACCA",
    "pick": "Player A ML + Player C ML",
    "odds": 2.45,
    "stake": 0.75,
    "date": "{today_iso}",
    "is_kombi": true
  }}
]
"""
    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(api_url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = full_reply
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        new_picks = json.loads(json_str)
                        for np in new_picks:
                            np["status"] = "PENDING"
                            np["sport"] = "Tennis"
                            try:
                                np["odds"] = float(str(np.get("odds", 1.75)).replace(",", "."))
                            except ValueError:
                                np["odds"] = 1.75
                            try:
                                np["stake"] = float(str(np.get("stake", 1.0)).replace(",", "."))
                            except ValueError:
                                np["stake"] = 1.0
                        combined_pending = history.get("pending", []) + new_picks
                        history["pending"] = deduplicate_picks(combined_pending)
                        save_history(history)
                        print(f"Tennis-Picks getrackt (jetzt {len(history['pending'])} offen).")
                    except Exception as je:
                        print(f"Fehler beim Parsen der Tracking-Picks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report)
                return
            elif res.status_code in [500, 502, 503, 504]:
                time.sleep(6)
            else:
                res.raise_for_status()
        except Exception as e:
            print(f"Versuch {attempt}/3 fehlgeschlagen: {e}")
            if attempt < 3:
                time.sleep(6)
            else:
                sys.exit(1)

if __name__ == "__main__":
    run_tennis_report()
