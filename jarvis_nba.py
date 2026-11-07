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

# ==========================================
# KONFIGURATION & CREDENTIALS
# ==========================================
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Sicheres Routing ins NBA-Thema
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NBA", "").strip()
    or os.environ.get("TELEGRAM_NBA_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_nba.json"
HISTORY_FILE = "nba_history.json"

# ==========================================
# STATE & TELEGRAM HILFSFUNKTIONEN
# ==========================================
def send_telegram(text, reply_to=None):
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="nba", reply_to=reply_to)
        if msg_id:
            return msg_id

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3900
    chunks = []
    rem_text = text.strip()
    while len(rem_text) > max_len:
        split_idx = rem_text.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = rem_text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(rem_text[:split_idx].strip())
        rem_text = rem_text[split_idx:].strip()
    if rem_text:
        chunks.append(rem_text)

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

def format_ticket_header(item):
    """Ermittelt das passende Schein-Label (POTD, ACCA, TOTALS, PROP) und Emoji."""
    raw_cat = str(item.get("category", "")).strip().upper()
    
    if "POTD" in raw_cat or "PICK OF THE DAY" in raw_cat:
        return "⭐ <b>POTD</b>"
    elif "ACCA" in raw_cat or item.get("is_kombi", False) or " // " in item.get("match", ""):
        return "🔥 <b>QUANT VALUE ACCA</b>"
    elif "PACE" in raw_cat or "TOTAL" in raw_cat:
        return "🎯 <b>PACE & TOTALS SPOTLIGHT</b>"
    elif "PROP" in raw_cat or "PLAYER" in raw_cat:
        return "👟 <b>PLAYER PROP SPOTLIGHT</b>"
    elif raw_cat:
        return f"🎯 <b>{raw_cat}</b>"
    else:
        return "🎯 <b>NBA VALUE SPOT</b>"

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return deduplicate_picks(data) if isinstance(data, list) else []
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        pending_list = deduplicate_picks(pending_list)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

def append_to_history(settled_items):
    if not settled_items:
        return
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    history = data
                elif isinstance(data, dict):
                    history = data.get("settled", [])
        except Exception:
            history = []
    history.extend(settled_items)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

# ==========================================
# 1. MORGEN-SETTLEMENT (ABRECHNUNG & BILANZ)
# ==========================================
def settle_pending_bets():
    pending = load_pending()
    if not pending:
        print("Keine offenen Wetten in pending_nba.json gefunden.")
        return

    print(f"Prüfe Abrechnung für {len(pending)} offene NBA-Picks...")
    remaining_pending = []
    settled_results = []

    for bet in pending:
        match = bet.get("match", "")
        pick = bet.get("pick", "")
        date_str = bet.get("date", "")
        is_kombi = bet.get("is_kombi", False) or "+" in pick or " // " in match

        prompt = f"""
Du bist 'JARVIS NBA SETTLEMENT AGENT'.
Ermittle via Google Search das offizielle Endergebnis des folgenden NBA-Spiels:
- Spiel: {match}
- Datum: {date_str}
- Wette: {pick}
- Ist Kombi: {is_kombi}

SUCH-ANWEISUNG:
Suche nach "{match} nba box score final" oder "{match} espn final".

AUFGABE:
1. Prüfe, ob das Spiel offiziell beendet ist (FINAL, inkl. OT).
2. Falls beendet: Ermittle den Endstand (z. B. '112:108') und bewerte, ob die Wette '{pick}' GEWONNEN (WON), VERLOREN (LOST) oder PUSH/VOID (VOID) ist.
3. Bei Kombiwetten: Wenn alle Beine gewonnen sind -> WON, sobald ein Bein verliert -> LOST. Bei mehreren Matches im Match-String (' // ') nenne für beide Partien den Score!
4. Falls das Spiel noch nicht beendet, verschoben oder noch nicht gespielt ist, antworte mit PENDING.
5. Gib maximal 1 prägnanten Begründungssatz an (max. 15 Wörter).

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder PENDING
SCORE: [Nur Zahlen/Ergebnis, z. B. 115:102 oder 110:108 // 122:115]
RESULT: WON oder LOST oder PENDING oder VOID
DETAILS: [Maximal 1 prägnanter Satz]
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(url, json=payload, timeout=45)
            if res.status_code == 200:
                ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                status = "PENDING"
                score = "-"
                result = "PENDING"
                details = ""

                for line in ans.split("\n"):
                    line = line.strip()
                    if line.startswith("STATUS:"):
                        status = line.replace("STATUS:", "").strip().upper()
                    elif line.startswith("SCORE:"):
                        score = line.replace("SCORE:", "").strip()
                    elif line.startswith("RESULT:"):
                        result = line.replace("RESULT:", "").strip().upper()
                    elif line.startswith("DETAILS:"):
                        details = line.replace("DETAILS:", "").strip()

                if status == "FINISHED" and result in ["WON", "LOST", "VOID"]:
                    try:
                        odds_val = float(str(bet.get("odds", "1.90")).replace(",", "."))
                    except ValueError:
                        odds_val = 1.90
                    try:
                        stake_val = float(str(bet.get("stake", "1.0")).replace(",", "."))
                    except ValueError:
                        stake_val = 1.0

                    if result == "WON":
                        pnl = round((odds_val - 1.0) * stake_val, 2)
                    elif result == "LOST":
                        pnl = round(-stake_val, 2)
                    else:
                        pnl = 0.0

                    bet["score"] = clean_score_text(score)
                    bet["details"] = clean_info_sentence(details)
                    bet["result"] = result
                    bet["status"] = result
                    bet["odds"] = odds_val
                    bet["stake"] = stake_val
                    bet["pnl"] = pnl
                    bet["sport"] = "NBA"

                    settled_results.append(bet)
                else:
                    remaining_pending.append(bet)
            else:
                remaining_pending.append(bet)
        except Exception as e:
            print(f"Fehler bei Abrechnung für {match}: {e}")
            remaining_pending.append(bet)

    save_pending(remaining_pending)

    if settled_results:
        append_to_history(settled_results)
        total_bets = len(settled_results)
        won_bets = sum(1 for r in settled_results if r["result"] == "WON")
        void_bets = sum(1 for r in settled_results if r["result"] == "VOID")
        valid_bets = total_bets - void_bets
        strike_rate = (won_bets / valid_bets) * 100 if valid_bets > 0 else 0

        total_staked = 0.0
        total_returned = 0.0

        for r in settled_results:
            odds_val = float(r.get("odds", 1.90))
            stake = float(r.get("stake", 1.0))
            total_staked += stake
            if r["result"] == "WON":
                total_returned += stake * odds_val
            elif r["result"] == "VOID":
                total_returned += stake

        profit = total_returned - total_staked
        roi = (profit / total_staked) * 100 if total_staked > 0 else 0
        profit_sign = "+" if profit >= 0 else ""
        profit_color = "🟢" if profit >= 0 else "🔴"

        lines = [
            "🏁 <b>JARVIS NBA — TAGESABSCHLUSS & BILANZ</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>ERGEBNISSE:</b>\n"
        ]

        for r in settled_results:
            status = r["result"]
            odds_val = float(r.get("odds", 1.90))
            stake_val = float(r.get("stake", 1.0))
            status_icon = "✅" if status == "WON" else ("🟡" if status == "VOID" else "❌")
            
            clean_score = r.get("score", "")
            score_disp = f" ({clean_score})" if clean_score else ""
            pnl_val = r.get("pnl", 0.0)
            pnl_str = f"+{pnl_val:.2f}u" if pnl_val >= 0 else f"{pnl_val:.2f}u"
            
            ticket_header = format_ticket_header(r)

            lines.append(f"{ticket_header} (<code>{stake_val:.2f}u</code> | <code>@{odds_val:.2f}</code>) ➔ {status_icon} <b>{status}</b> (<code>{pnl_str}</code>)")
            lines.append(f"• <b>Match:</b> {r['match']}{score_disp}")
            lines.append(f"• <b>Tipp:</b> {r['pick']}")
            
            if r.get("details"):
                lines.append(f"• <i>{r['details']}</i>")
            lines.append("")

        push_str = f" - {void_bets}P" if void_bets > 0 else ""
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📊 <b>BILANZ & KENNZAHLEN</b>")
        lines.append(f"• <b>Trefferquote:</b> {won_bets}/{valid_bets} ({strike_rate:.1f}%){push_str}")
        lines.append(f"• <b>Einsatz / Rücklauf:</b> {total_staked:.2f}u ➔ {total_returned:.2f}u")
        lines.append(f"• {profit_color} <b>Netto-Ergebnis:</b> <b>{profit_sign}{profit:.2f} Units</b>")
        lines.append(f"• <b>ROI:</b> <b>{profit_sign}{roi:.1f}%</b>")
        lines.append("\n📁 <i>Alle Wetten wurden in nba_history.json archiviert.</i>")

        send_telegram("\n".join(lines).strip())
        print("NBA-Abrechnung erfolgreich gepostet.")

# ==========================================
# 2. THE ODDS API & PICKS GENERIERUNG
# ==========================================
def fetch_nba_odds():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
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
            cutoff = now_utc + timedelta(hours=18)
            for m in res.json():
                commence = datetime.fromisoformat(m["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence <= cutoff:
                    time_str = commence.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                    bookies = m.get("bookmakers", [])
                    if not bookies:
                        continue
                    m_details = []
                    for mk in bookies[0].get("markets", []):
                        outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in mk.get("outcomes", [])]
                        m_details.append(f"{mk.get('key')}: {', '.join(outcomes)}")
                    events.append(f"{m['home_team']} vs. {m['away_team']} ({time_str}) | {' // '.join(m_details)}")
            return "\n".join(events[:40])
    except Exception as e:
        print(f"Fehler bei NBA Odds: {e}")
    return ""

def run_nba_intel():
    odds_data = fetch_nba_odds()
    if not odds_data:
        print("Keine NBA-Spiele im Zeitfenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS NBA QUANT ARCHITECT'.
Erstelle für heute ({today_str}) das NBA-Value-Dossier.

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
   - Quoten und Stakes immer in <code>...</code> setzen (z. B. <code>@1.90</code>, <code>1.50u</code>).
   - Trennlinie IMMER exakt 20 Zeichen: '━━━━━━━━━━━━━━━━━━━━'.
   - Begründungen im Deep Dive kurz und schlüssig in maximal 2 Sätzen halten.

⛔ STRIKTE QUANT- & VETO-REGELN:
1. Keine Quoten unter 1.40 bei Einzel-Tipps.
2. Form- & Verletzungs-Check via Google Search (Verletzungen, Rest Advantage, B2B).
3. Bei Player Props: Nur Starter mit fester Rotation.

EXAKTES HTML-AUSGABEFORMAT:
🏀 <b>JARVIS NBA — TAGESEMPFEHLUNGEN ({today_str})</b>
━━━━━━━━━━━━━━━━━━━━
📋 <b>WETTSCHEINE AUF EINEN BLICK:</b>

⭐ <b>POTD (<code>1.50u</code> | <code>@[Quote]</code>)</b>
- <b>[Heim] vs. [Gast]</b> ➔ <i>[Spread / Total / ML]</i>

🔥 <b>QUANT VALUE ACCA (<code>1.00u</code> | Gesamt: <code>@[Quote]</code>)</b>
- [Heim] vs. [Gast] ➔ <i>[Tipp 1]</i>
- [Heim] vs. [Gast] ➔ <i>[Tipp 2]</i>

🎯 <b>PACE & TOTALS SPOTLIGHT (<code>0.75u</code> | <code>@[Quote]</code>)</b>
- <b>[Heim] vs. [Gast]</b> ➔ <i>[Over/Under Tipp]</i>

👟 <b>PLAYER PROP SPOTLIGHT (<code>0.75u</code> | <code>@[Quote]</code>)</b>
- [Spieler] ([Team]) ➔ <i>[Punkte / Rebounds / Assists / 3PT]</i>

━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>

🔎 <b>POTD: [Heim] vs. [Gast]</b>
- <b>Edge:</b> [Net-Rating Vorteil / Fair-Quote]
- <b>Logik:</b> [Maximal 2 präzise Sätze zu Matchup, Pace und Defense-Matchups]

🔎 <b>Acca & Spotlights Begründung:</b>
- [Team 1 / Pick 1]: [1-2 Sätze Begründung]
- [Totals / Prop]: [1-2 Sätze Begründung]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NBA",
    "category": "POTD",
    "pick": "Team A -3.5",
    "odds": 1.90,
    "stake": 1.5,
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "Team A vs Team B // Team C vs Team D",
    "sport": "NBA",
    "category": "QUANT VALUE ACCA",
    "pick": "Team A ML + Team C ML",
    "odds": 2.10,
    "stake": 1.0,
    "date": "{today_iso}",
    "is_kombi": true
  }},
  {{
    "match": "Team A vs Team B",
    "sport": "NBA",
    "category": "PACE & TOTALS SPOTLIGHT",
    "pick": "Over 224.5",
    "odds": 1.90,
    "stake": 0.75,
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "Team A vs Team B",
    "sport": "NBA",
    "category": "PLAYER PROP SPOTLIGHT",
    "pick": "Spieler X Over 24.5 Punkte",
    "odds": 1.85,
    "stake": 0.75,
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
                            np["sport"] = "NBA"
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
                        print(f"{len(new_picks)} NBA-Picks in {PENDING_FILE} gesichert.")
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

# ==========================================
# 3. HAUPTSTEUERUNG MIT ZEIT-WEICHE
# ==========================================
def main():
    now_berlin = datetime.now(LOCAL_TZ)
    current_hour = now_berlin.hour

    print(f"=== JARVIS NBA ENGINE START [{now_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}] ===")

    # 1. Abrechnung läuft morgens oder per manuellem Dispatch
    settle_pending_bets()

    # 2. Picks werden im Abendfenster (ab 16:00 Uhr MEZ) generiert
    if current_hour >= 16:
        print(f"Abend-Fenster aktiv ({current_hour} Uhr MEZ): Starte Quotenabfrage & Dossier-Erstellung...")
        run_nba_intel()
    else:
        print(f"Morgen-Fenster aktiv ({current_hour} Uhr MEZ): Nur Abrechnung ausgeführt. Picks folgen am späten Nachmittag.")

if __name__ == "__main__":
    main()
