import os
import sys
import json
import time
import re
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sicheres Routing ins NFL-Thema
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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine NFL Thread-ID konfiguriert.")
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
        print(f"[Telegram] Sende-Fehler: {e}")
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

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw = data if isinstance(data, list) else data.get("pending", [])
            return deduplicate_picks(raw)
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        unique_list = deduplicate_picks(pending_list)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(unique_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")
        return []

def save_history(history_list):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

def settle_pending_picks():
    pending = load_pending()
    if not pending:
        print("Keine offenen NFL-Picks zur Abrechnung.")
        return

    history = load_history()
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
Du bist 'JARVIS NFL SETTLEMENT AGENT'.
Recherchiere via Google Search das offizielle Endergebnis des folgenden NFL-Matches bzw. der Wette:
Match: {match}
Tipp: {pick}
Datum: {date_str}
Ist Kombi: {is_kombi}

REGELN FÜR NFL:
1. Prüfe, ob das Spiel beendet ist (FINAL). Falls noch live oder nicht begonnen -> PENDING.
2. Bei Spielerwetten (Player Props wie Passing/Rushing Yards, Touchdowns): Prüfe den exakten Boxscore.
3. Bei Spreads & Over/Under: Exaktes Endergebnis inklusive Overtime berücksichtigen.
4. Bei Push / Line genau getroffen -> VOID.
5. Bei Kombiwetten: Alle Beine müssen gewinnen -> WON. Sobald ein Bein verliert -> LOST.
6. Gib genau 1 kurzen Satz als Begründung an (max. 15 Wörter).

Antworte strikt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: [Endergebnis, z.B. 24:17 oder Spieler-Stats]
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
                    item["sport"] = "NFL"

                    try:
                        odds_val = float(str(item.get("odds", "1.90")).replace(",", "."))
                    except ValueError:
                        odds_val = 1.90
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
            print(f"Fehler bei NFL-Settle {match}: {e}")
            still_pending.append(item)

    if settled_now:
        history.extend(settled_now)
        save_history(history)
        save_pending(still_pending)

        total_tickets = len(settled_now)
        won_tickets = sum(1 for p in settled_now if p["status"] == "WON")
        void_tickets = sum(1 for p in settled_now if p["status"] == "VOID")

        total_staked = 0.0
        total_returned = 0.0

        today_display = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
        msg = f"🏈 <b>JARVIS NFL ABRECHNUNG</b>\n"
        msg += f"<i>Offizielle Auswertung der NFL-Slates ({today_display})</i>\n"

        for p in settled_now:
            odds_val = float(p.get("odds", 1.90))
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
                outcome_str = "<b>PUSH / VOID (0.0u)</b>"
                total_returned += ret
            else:
                icon = "❌"
                outcome_str = f"<b>LOST (-{stake:.2f}u)</b>"

            score_display = f" | <b>{p.get('score')}</b>" if p.get('score') else ""

            msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"{icon} <b>{p['match']}</b>{score_display}\n"
            msg += f"   ↳ <i>{p['pick']}</i> (@{odds_val:.2f}) ➔ {icon} {outcome_str}\n"
            if p.get("info"):
                msg += f"   • {p['info']}\n"

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
    else:
        save_pending(still_pending)

def fetch_nfl_odds():
    url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            events = []
            now_utc = datetime.now(timezone.utc)
            cutoff = now_utc + timedelta(hours=36)
            for m in res.json():
                commence = datetime.fromisoformat(m["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence <= cutoff:
                    time_str = commence.astimezone(LOCAL_TZ).strftime("%a %H:%M Uhr")
                    bookies = m.get("bookmakers", [])
                    if not bookies:
                        continue
                    m_details = []
                    for mk in bookies[0].get("markets", []):
                        outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in mk.get("outcomes", [])]
                        m_details.append(f"{mk.get('key')}: {', '.join(outcomes)}")
                    events.append(f"{m['home_team']} vs. {m['away_team']} ({time_str}) | {' // '.join(m_details)}")
            return "\n".join(events[:35])
    except Exception as e:
        print(f"Fehler bei NFL Odds: {e}")
    return ""

def run_nfl_intel():
    odds_data = fetch_nfl_odds()
    if not odds_data:
        print("Keine anstehenden NFL-Spiele im Zeitfenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS NFL QUANT' – Spezialist für quantitative NFL-Modellierung (EPA/Play, Dropback Success Rate, Neutral Pace, DVOA, Injury-Impact).
Erstelle für den anstehenden NFL-Spieltag ({today_str}) ein fundiertes Value-Dossier.

VERFÜGBARE PARTIEN & QUOTEN:
{odds_data}

RICHTLINIEN & MÄRKTE:
- Wähle ausschließlich Partien aus der obigen Liste.
- Analysiere Trench-Matchups (Pass Rush vs. Pass Block Win Rate), Key Numbers (3, 7, 6, 10, 4) und Wetter/Injuries via Google Search.
- DYNAMISCHE ACCA: Begrenze dich beim Kombi-Ticket NICHT künstlich auf 2 Spiele. Kombiniere 2 bis 3 Partien, sofern sie mathematischen Vorteil (+EV) bieten.
- BUCHMACHER-ALTERNATIVE: Gib für jeden Spread/Total-Pick immer eine Standard-Alternative für europäische Bookies an.
- VALUE-GRENZE: Weise für jeden Tipp eine Mindestquote aus ('Spielbar bis @ X.XX').
- Mindestquote beachten: Keine Quoten unter 1.35!

================================================================================
STRIKTE TELEGRAM-FORMATIERUNG (CARD-DESIGN):
================================================================================
- KEINE doppelten Leerzeilen zwischen Absätzen!
- Aufzählungen beginnen IMMER direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch danach.
- Sub-Punkte und Auswahlen rücken sauber mit '   ↳ ' ein (z. B. '   ↳ <b>Haupt-Pick:</b> ...').
- Trennlinie IMMER exakt 20 Zeichen: '━━━━━━━━━━━━━━━━━━━━'
- Halte die Begründungen präzise und fundiert in 2-3 Sätzen.
- Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🏈 <b>JARVIS NFL INTEL DOSSIER</b>
<i>Advanced Analytics • EPA/Play Edge • Key-Number Modeling</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>NFL PICK OF THE DAY (Single Bet)</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
   ↳ <b>Haupt-Pick:</b> <b>[Spread / Total / Moneyline]</b> @ [Quote]
   ↳ <i>Buchmacher-Alternative:</i> [Klassische Standard-Linie] @ [Quote]
• <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 1.5 Units
• <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
• <b>Edge:</b> [EPA/Play Differenz, Success Rate, Trench-Matchup, Roster-Status kompakt in 2-3 Sätzen]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA ([Anzahl]-er Kombi)</b>
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• <b>Gesamtquote:</b> <b>@[Quote]</b>
• <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 0.75 Units
• <b>Kombi-Logik:</b> [Warum diese Kombination mathematisch korreliert oder starken Value bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>TOTALS & PACE SPOTLIGHT</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
   ↳ <b>Pick:</b> <b>[Over/Under Wette / Team-Total]</b> @ [Quote]
   ↳ <i>Alternative:</i> [Standard-Linie] @ [Quote]
• <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 1.0 Units
• <b>Rationale:</b> [Neutral Pace, Red-Zone Conversion Efficiency, Passing-Downs Explosiveness]

━━━━━━━━━━━━━━━━━━━━
👟 <b>NFL PLAYER PROP SPOTLIGHT</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
   ↳ <b>Pick:</b> <b>[Spielername: Passing / Rushing / Receiving Yards / Anytime TD]</b> @ [Quote]
   ↳ <i>Alternative:</i> [Alternative Linie] @ [Quote]
• <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 0.75 Units
• <b>Rationale:</b> [Target Share, aDOT, Coverage-Schwächen des Gegners]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NFL",
    "category": "POTD",
    "pick": "Team A -2.5",
    "odds": 1.90,
    "stake": 1.5,
    "date": "{today_iso}",
    "is_kombi": false
  }}
]
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = full_reply
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        new_picks = json.loads(json_str)
                        pending = load_pending()
                        for np in new_picks:
                            np["status"] = "PENDING"
                            np["sport"] = "NFL"
                            try:
                                np["odds"] = float(str(np.get("odds", 1.90)).replace(",", "."))
                            except ValueError:
                                np["odds"] = 1.90
                            try:
                                np["stake"] = float(str(np.get("stake", 1.0)).replace(",", "."))
                            except ValueError:
                                np["stake"] = 1.0
                        pending.extend(new_picks)
                        save_pending(pending)
                        print(f"{len(new_picks)} NFL-Picks getrackt.")
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
    # 1. Abrechnung IMMER zuerst prüfen und ausführen
    settle_pending_picks()

    # 2. Prüfen, ob es ein reiner Settle-Run ist oder die Uhrzeit vor 16:00 Uhr MEZ liegt
    is_settle_only = "--settle-only" in sys.argv
    now_hour = datetime.now(LOCAL_TZ).hour

    if is_settle_only or now_hour < 16:
        print(f"Morgen-/Settle-Lauf abgeschlossen (Uhrzeit: {now_hour}:00 Uhr MEZ, settle_only={is_settle_only}). Keine Picks generiert.")
        sys.exit(0)

    # 3. Dossier wird ausschließlich ab 16:00 Uhr MEZ generiert
    run_nfl_intel()
