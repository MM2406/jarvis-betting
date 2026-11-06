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

# Sichere Fallback-Kette für das Tennis-Topic
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_TENNIS_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_TENNIS", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "tennis_history.json"

def make_progress_bar(percentage, segments=10):
    clamped = max(0.0, min(100.0, float(percentage)))
    filled = int(round((clamped / 100.0) * segments))
    empty = segments - filled
    return f"[{'🟩' * filled}{'⬜' * empty}]"

def send_telegram(text, reply_to=None):
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="tennis", reply_to=reply_to)
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

        for p in settled_now:
            odds_val = float(p.get("odds", 1.0))
            stake = float(p.get("stake", 1.0))
            total_staked += stake

            status = p["status"]
            if status == "WON":
                ret = stake * odds_val
                total_returned += ret
            elif status == "VOID":
                total_returned += stake

        net_profit = total_returned - total_staked
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        valid_tickets = total_tickets - void_tickets
        hit_rate = (won_tickets / valid_tickets * 100) if valid_tickets > 0 else 0.0
        sign = "+" if net_profit >= 0 else ""
        profit_color = "🟢" if net_profit >= 0 else "🔴"

        lines = [
            "🏁 <b>JARVIS TENNIS — TAGESABSCHLUSS & BILANZ</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>ERGEBNISSE:</b>\n"
        ]

        for p in settled_now:
            status = p["status"]
            odds_val = float(p.get("odds", 1.0))
            stake = float(p.get("stake", 1.0))
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
        lines.append("\n📁 <i>Alle Tickets wurden in tennis_history.json archiviert.</i>")

        send_telegram("\n".join(lines).strip())

    return history

def fetch_tennis_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=36)

    active_tennis_sports = []
    try:
        sports_url = "https://api.the-odds-api.com/v4/sports/"
        res_sports = requests.get(sports_url, params={"apiKey": ODDS_API_KEY}, timeout=10)
        if res_sports.status_code == 200:
            for s in res_sports.json():
                if s.get("group") == "Tennis" and s.get("active", False):
                    active_tennis_sports.append(s.get("key"))
    except Exception as e:
        print(f"Fehler beim Abrufen der aktiven Tennis-Ligen: {e}")

    if not active_tennis_sports:
        active_tennis_sports = ["tennis_atp", "tennis_wta"]

    print(f"Aktive Tennis-Keys: {active_tennis_sports}")

    for sport in active_tennis_sports:
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
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%a %H:%M Uhr")
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

    print(f"Gefundene Tennis-Partien: {len(all_events)}")
    return "\n".join(all_events[:45])

def run_tennis_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    slate_name = "Tages-Slate (Europa / Asien)" if now_hour < 15 else "Abend- & Nacht-Slate (Übersee)"

    odds_data = fetch_tennis_odds()
    if not odds_data or len(odds_data.strip()) < 20:
        print("Keine Tennis-Partien im aktuellen Zeitfenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS TENNIS QUANT ARCHITECT'.
Erstelle für die aktuelle Slate ({today_str} – {slate_name}) das Tennis-Value-Dossier.

VERFÜGBARE MATCHES & ECHTE BUCHMACHERQUOTEN:
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
2. Analysiere Serve/Return Dominance Ratio, Belag-Profil (Hardcourt/Clay/Grass/Indoor), 1st Serve In % und H2H via Google Search.

EXAKTES HTML-AUSGABEFORMAT:
🎾 <b>JARVIS TENNIS — TAGESEMPFEHLUNGEN ({today_str})</b>
<i>{slate_name}</i>
━━━━━━━━━━━━━━━━━━━━
📋 <b>WETTSCHEINE AUF EINEN BLICK:</b>

⭐ <b>POTD (<code>1.50u</code> | <code>@[Quote]</code>)</b>
• <b>[Spieler A] vs. [Spieler B]</b> ➔ <i>[Sieg / Games-Handicap / Satz]</i>

🔥 <b>QUANT VALUE ACCA (<code>1.00u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Spieler A] vs. [Spieler B] ➔ <i>[Tipp 1]</i>
• [Spieler C] vs. [Spieler D] ➔ <i>[Tipp 2]</i>

🎯 <b>TOTALS SPOTLIGHT (<code>0.75u</code> | <code>@[Quote]</code>)</b>
• <b>[Spieler A] vs. [Spieler B]</b> ➔ <i>[Over/Under Games / Sätze]</i>

━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>

🔎 <b>POTD: [Spieler A] vs. [Spieler B]</b>
• <b>Edge:</b> [Dominance Ratio Vorteil / Fair-Quote]
• <b>Logik:</b> [Maximal 2 präzise Sätze zu Belags-Mismatch, Aufschlag-Dominanz und Return-Statistik]

🔎 <b>Acca & Spotlight Begründung:</b>
• [Pick 1]: [1-2 Sätze Begründung]
• [Totals]: [1-2 Sätze Begründung]

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
                        print(f"Tennis-Picks in {HISTORY_FILE} gesichert.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der Tennis-Picks: {je}")

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
