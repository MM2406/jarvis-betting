import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Sichere Anbindung der zentralen Telegram-Hilfsfunktion
try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sichere Fallback-Kette für das Europa-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_EURO_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_EUROPA", "").strip()
    or os.environ.get("TELEGRAM_THREAD_EURO", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "euro_history.json"

EURO_SPORTS = [
    "basketball_euroleague",
    "icehockey_germany_del",
    "icehockey_sweden_shl"
]

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram(text):
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_EURO_THREAD_ID")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine Europa Thread-ID vorhanden. Senden in den Hauptchat blockiert.")
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

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"settled": [], "pending": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("settled", [])
                data.setdefault("pending", [])
                return data
            elif isinstance(data, list):
                return {"settled": data, "pending": []}
    except Exception as e:
        print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")
    return {"settled": [], "pending": []}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

def settle_pending_picks(history):
    pending = history.get("pending", [])
    if not pending:
        print("Keine offenen Euro-Picks zur Auswertung.")
        return history

    still_pending = []
    settled_now = []

    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis fuer folgendes Spiel:
Match: {item.get('match')}
Wettbewerb: {item.get('sport')}
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Pruefe, ob das Match bereits regulaer beendet ist (FINAL, inkl. OT). Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Push (z.B. Handicap Unentschieden) gib 'VOID' aus.
4. Gib eine kurze, praezise Erklaerung an (Spielstand, Schwaechephasen, OT).

Antworte exakt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: [Endergebnis]
INFO: [1-2 Saetze Erklaerung/Begruendung]
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
                    item["sport"] = "Euro-Hoops & Ice"
                    
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
            print(f"Fehler bei Euro-Settle {item.get('match')}: {e}")
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
        msg = f"🇪🇺 <b>JARVIS EURO-HOOPS & ICE ABRECHNUNG</b>\n"
        msg += f"<i>Abrechnung der Partien vom {today_display}</i>\n"

        for p in settled_now:
            odds_val = float(p.get("odds", 1.0))
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

    return history

def fetch_euro_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=15)

    for sport in EURO_SPORTS:
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
                        all_events.append(f"[{sport}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(odds_details)}")
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Euro-Partien: {len(all_events)}")
    return "\n".join(all_events[:45])

def run_euro_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 12:
        print("Morgen-Run: Nur Abrechnung durchgefuehrt.")
        return

    odds_data = fetch_euro_odds()
    if not odds_data:
        print("Keine europaeischen Basketball- oder Eishockeyspiele heute.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS EURO INTEL' – Experte fuer EuroLeague Basketball sowie deutsches (DEL) und schwedisches (SHL) Eishockey.
Erstelle fuer heute ({today_str}) ein quantitatives Value-Dossier.

VERFUEGBARE PARTIEN & QUOTEN:
{odds_data}

RICHTLINIEN & MAERKTE:
- Waehle ausschliesslich Partien aus der obigen Liste.
- Bei Eishockey klar deklarieren: Regulaere Spielzeit (3-Weg) oder inkl. Overtime.
- DYNAMISCHE ACCA: Kombiniere flexibel 2 bis 4 Spiele mit rechnerischem Vorteil (+EV). Kein starres 2-Spiele-Limit.
- BUCHMACHER-ALTERNATIVE: Gib fuer jeden Haupttipp immer eine Standard-Alternative an.
- VALUE-GRENZE: Weise fuer jeden Tipp eine Mindestquote aus ('Spielbar bis @ X.XX').
- UNITS:
  • Pick of the Day: 1.0 bis 2.0 Units
  • Value Acca: 0.5 bis 1.0 Units
  • Special Matchup Spotlight: 0.5 bis 1.0 Units

FORMATIERUNGS-REGELN FUER TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzaehlung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🇪🇺 <b>JARVIS EURO-HOOPS & ICE DOSSIER</b>
<i>EuroLeague • DEL • SHL Advanced Quant-Models</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>EURO PICK OF THE DAY (Single Bet)</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Liga] [Heimteam] vs. [Auswaertsteam]
➔ <b>Haupt-Pick:</b> <b>[Markt & Tipp]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [1.0 - 2.0] Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [Defensiv-Ratings, Formkurve, Heimstaerke in europaeischen Hallen]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA ([Anzahl]-er Kombi)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 3]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
[... ggf. Bein 4 ergaenzen falls Value vorhanden ...]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Kombi-Logik:</b> [Warum diese Kombination mathematisch korreliert oder unabhaengig starken Value bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>SPECIAL MATCHUP SPOTLIGHT</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswaertsteam]
➔ <b>Pick:</b> <b>[Over/Under / Handicap / Team Total]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [Taktische Besonderheit, Matchup-Vorteile, Quoten-Diskrepanz]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "Euro-Hoops & Ice",
    "pick": "Team A Sieg",
    "odds": 1.75,
    "stake": 1.0,
    "date": "{today_iso}"
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
                            np["sport"] = "Euro-Hoops & Ice"
                        history["pending"].extend(new_picks)
                        save_history(history)
                        print(f"{len(new_picks)} Euro-Picks hinzugefuegt.")
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
    run_euro_report()
