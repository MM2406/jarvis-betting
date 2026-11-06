import os
import sys
import json
import time
import re
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

try:
    from telegram_formatter import send_to_sport_channel
except ImportError:
    send_to_sport_channel = None

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

def send_telegram(text, reply_to=None):
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="euro", reply_to=reply_to)
        if msg_id:
            return msg_id

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3900
    chunks = []
    while len(text) > max_len:
        split_idx = text.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    if text:
        chunks.append(text)

    last_msg_id = None
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if TELEGRAM_THREAD_ID:
            try:
                payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
            except ValueError:
                pass
        if reply_to:
            payload["reply_to_message_id"] = int(reply_to)

        try:
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code != 200:
                payload.pop("parse_mode", None)
                res2 = requests.post(url, json=payload, timeout=25)
                if res2.status_code == 200:
                    last_msg_id = res2.json().get("result", {}).get("message_id")
            else:
                last_msg_id = res.json().get("result", {}).get("message_id")
        except Exception as e:
            print(f"[Telegram] Netzwerkfehler: {e}")

    return last_msg_id

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
    return re.sub(r"\s*\([^)]*\)", "", raw_score).strip()

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
        print("Keine offenen Euro-Picks zur Auswertung.")
        return history

    pending = deduplicate_picks(pending)
    still_pending = []
    settled_now = []

    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes Spiel:
Match: {item.get('match')}
Wettbewerb: {item.get('sport')}
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob das Match bereits beendet ist (FINAL, inkl. OT falls relevant). Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Push (z. B. Handicap Unentschieden oder exakte Line) gib 'VOID' aus.
4. Gib nur EINEN kurzen Satz Begründung an (max. 15 Wörter).

Antworte exakt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: [Nur Zahlen/Ergebnis, z.B. 84:78 oder 3:2 OT]
INFO: [Maximal 1 prägnanter Satz]
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

        for p in settled_now:
            odds_val = float(p.get("odds", 1.0))
            stake = float(p.get("stake", 1.0))
            total_staked += stake

            status = p["status"]
            if status == "WON":
                total_returned += stake * odds_val
            elif status == "VOID":
                total_returned += stake

        net_profit = total_returned - total_staked
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        valid_tickets = total_tickets - void_tickets
        hit_rate = (won_tickets / valid_tickets * 100) if valid_tickets > 0 else 0.0
        sign = "+" if net_profit >= 0 else ""
        profit_color = "🟢" if net_profit >= 0 else "🔴"

        lines = [
            "🏁 <b>JARVIS EURO-HOOPS & ICE — TAGESABSCHLUSS & BILANZ</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>ERGEBNISSE:</b>\n"
        ]

        for p in settled_now:
            status = p["status"]
            odds_val = float(p.get("odds", 1.0))
            icon = "✅" if status == "WON" else ("🟡" if status == "VOID" else "❌")
            clean_score = clean_score_text(p.get("score", ""))
            score_disp = f" ({clean_score})" if clean_score else ""
            pnl_val = p.get("pnl", 0.0)
            pnl_str = f"+{pnl_val:.2f}u" if pnl_val >= 0 else f"{pnl_val:.2f}u"

            lines.append(f"{icon} <b>{p['match']}</b>{score_disp}")
            lines.append(f"• <b>Tipp:</b> {p['pick']} (<code>@{odds_val:.2f}</code>) ➔ <b>{status}</b> (<code>{pnl_str}</code>)")
            clean_info = clean_info_sentence(p.get("info", ""))
            if clean_info:
                lines.append(f"• <i>{clean_info}</i>")
            lines.append("")

        push_str = f" - {void_tickets}P" if void_tickets > 0 else ""
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📊 <b>BILANZ & KENNZAHLEN</b>")
        lines.append(f"• <b>Trefferquote:</b> {won_tickets}/{total_tickets - void_tickets} ({hit_rate:.1f}%){push_str}")
        lines.append(f"• <b>Einsatz / Rücklauf:</b> {total_staked:.2f}u ➔ {total_returned:.2f}u")
        lines.append(f"• {profit_color} <b>Netto-Ertrag:</b> <b>{sign}{net_profit:.2f} Units</b>")
        lines.append(f"• <b>ROI:</b> <b>{sign}{roi:.1f}%</b>")
        lines.append("\n📁 <i>Alle Tickets wurden in euro_history.json archiviert.</i>")

        send_telegram("\n".join(lines).strip())

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
        print("Morgen-Run: Nur Abrechnung durchgeführt.")
        return

    odds_data = fetch_euro_odds()
    if not odds_data:
        print("Keine europäischen Basketball- oder Eishockeyspiele heute.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS EURO INTEL ARCHITECT' – Experte für EuroLeague Basketball sowie deutsches (DEL) und schwedisches (SHL) Eishockey.
Erstelle für heute ({today_str}) das quantitative Value-Dossier.

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN:
{odds_data}

================================================================================
STRIKTE ARCHITEKTUR & LAYOUT-REGELN (PICKS FIRST):
================================================================================
1. PICKS FIRST:
   - Alle spielfertigen Wettscheine stehen ZWINGEND GANZ OBEN direkt unter dem Header!
   - Erst DANACH folgt die Trennlinie '━━━━━━━━━━━━━━━━━━━━' und der Abschnitt 'ANALYSEN & MODELL-LOGIK (DEEP DIVE)'.
2. LÄNGEN-LIMIT:
   - Der GESAMTE Text vor '---JSON_TRACKING---' darf maximal 3.400 Zeichen umfassen.
3. FORMATIERUNG:
   - Quoten und Stakes immer in <code>...</code> setzen (z. B. <code>@1.75</code>, <code>1.50u</code>).
   - Trennlinie IMMER exakt 20 Zeichen: '━━━━━━━━━━━━━━━━━━━━'.
   - Begründungen im Deep Dive kurz und schlüssig in maximal 2 Sätzen halten.

⛔ STRIKTE QUANT- & VETO-REGELN:
1. Keine Quoten unter 1.40 bei Einzel-Tipps.
2. Bei Eishockey klar deklarieren: Reguläre Spielzeit (3-Weg) oder inkl. Overtime/Shootout (2-Weg).
3. DYNAMISCHE ACCA: Kombiniere 2 bis 3 Spiele mit klarem mathematischem Vorteil (+EV).

EXAKTES HTML-AUSGABEFORMAT:
🇪🇺 <b>JARVIS EURO-HOOPS & ICE — TAGESEMPFEHLUNGEN ({today_str})</b>
━━━━━━━━━━━━━━━━━━━━
📋 <b>WETTSCHEINE AUF EINEN BLICK:</b>

⭐ <b>EURO PICK OF THE DAY (<code>1.50u</code> | <code>@[Quote]</code>)</b>
• <b>[Heim] vs. [Gast]</b> ➔ <i>[Markt & Tipp]</i>

🔥 <b>QUANT VALUE ACCA (<code>1.00u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Heim] vs. [Gast] ➔ <i>[Tipp 1]</i>
• [Heim] vs. [Gast] ➔ <i>[Tipp 2]</i>

🎯 <b>SPECIAL MATCHUP SPOTLIGHT (<code>0.75u</code> | <code>@[Quote]</code>)</b>
• <b>[Heim] vs. [Gast]</b> ➔ <i>[Over/Under / Handicap / Team Total]</i>

━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>

🔎 <b>POTD: [Heim] vs. [Gast]</b>
• <b>Edge:</b> [Defensiv-Rating Differenz / Fair-Quote]
• <b>Logik:</b> [Maximal 2 präzise Sätze zu Pace, Heimstärke und Matchup-Vorteilen]

🔎 <b>Acca & Spotlight Begründung:</b>
• [Pick 1]: [1-2 Sätze Begründung]
• [Special Spotlight]: [1-2 Sätze Begründung]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "Euro-Hoops & Ice",
    "category": "POTD",
    "pick": "Team A Sieg",
    "odds": 1.75,
    "stake": 1.5,
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "Team A vs Team B // Team C vs Team D",
    "sport": "Euro-Hoops & Ice",
    "category": "ACCA",
    "pick": "Team A ML + Team C ML",
    "odds": 2.45,
    "stake": 1.0,
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
                            np["sport"] = "Euro-Hoops & Ice"
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
                        print(f"Euro-Picks in {HISTORY_FILE} gesichert.")
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
