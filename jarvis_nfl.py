import os
import sys
import json
import time
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

# Sicheres Routing ins NFL-Thema
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NFL", "").strip()
    or os.environ.get("TELEGRAM_NFL_THREAD_ID", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_nfl.json"
HISTORY_FILE = "nfl_history.json"

# ==========================================
# STATE & TELEGRAM HILFSFUNKTIONEN
# ==========================================
def send_telegram(text, reply_to=None):
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="nfl", reply_to=reply_to)
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

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

def save_to_history(settled_list):
    if not settled_list:
        return
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    history = data
        except Exception as e:
            print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")

    history.extend(settled_list)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"{len(settled_list)} NFL-Wetten in {HISTORY_FILE} archiviert.")
    except Exception as e:
        print(f"Fehler beim Speichern in {HISTORY_FILE}: {e}")

# ==========================================
# 1. MORGEN-SETTLEMENT (ABRECHNUNG & BILANZ)
# ==========================================
def settle_pending_bets():
    pending = load_pending()
    if not pending:
        print("Keine offenen Wetten in pending_nfl.json gefunden.")
        return

    print(f"Prüfe Abrechnung für {len(pending)} offene NFL-Picks...")
    remaining_pending = []
    settled_results = []

    for bet in pending:
        match = bet.get("match", "")
        pick = bet.get("pick", "")
        odds = bet.get("odds", "-")
        date_str = bet.get("date", "")
        is_kombi = bet.get("is_kombi", False) or "kombi" in bet.get("category", "").lower() or "+" in pick

        prompt = f"""
Du bist ein Sport-Abrechnungssystem für American Football (NFL).
Ermittle via Google Search die offiziellen Endergebnisse für folgende NFL-Wette:
- Spiel / Begegnungen: {match}
- Datum: {date_str}
- Wette: {pick}
- Ist Kombiwette: {is_kombi}

REGELN FÜR NFL:
- Alle Spreads, Over/Under und Siegwetten gelten inklusive Overtime (OT).
- Touchdowns, Passing/Rushing/Receiving Yards zählen bis zum offiziellen Spielende.

AUFGABE:
1. Prüfe, ob alle relevanten Spiele offiziell beendet sind (FINAL).
2. Falls eine Kombiwette vorliegt:
   - Werte jedes einzelne Bein separat aus.
   - Alle Beine gewonnen -> WON
   - Mindestens ein Bein verloren -> LOST
3. Falls Einzelwette: Ermittle Endstand (z. B. 24:20) und bewerte WON oder LOST.
4. Falls Spiele noch laufen oder ausstehen -> STATUS: PENDING

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder PENDING
RESULT: WON oder LOST oder PENDING
LEGS_WON: Anzahl der gewonnenen Beine
LEGS_TOTAL: Gesamtanzahl der Beine
DETAILS:
- Bein 1: Team A vs Team B | Ergebnis: X:Y | WON oder LOST
- Bein 2: ...
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                status = "PENDING"
                result = "PENDING"
                legs_won = 0
                legs_total = 1
                details_lines = []
                in_details = False

                for line in ans.split("\n"):
                    line_s = line.strip()
                    if line_s.startswith("STATUS:"):
                        status = line_s.replace("STATUS:", "").strip().upper()
                    elif line_s.startswith("RESULT:"):
                        result = line_s.replace("RESULT:", "").strip().upper()
                    elif line_s.startswith("LEGS_WON:"):
                        try:
                            legs_won = int(line_s.replace("LEGS_WON:", "").strip())
                        except ValueError:
                            pass
                    elif line_s.startswith("LEGS_TOTAL:"):
                        try:
                            legs_total = int(line_s.replace("LEGS_TOTAL:", "").strip())
                        except ValueError:
                            pass
                    elif line_s.startswith("DETAILS:"):
                        in_details = True
                    elif in_details and line_s:
                        details_lines.append(line_s)

                if status == "FINISHED" and result in ["WON", "LOST"]:
                    try:
                        odds_val = float(str(odds).replace(",", "."))
                    except ValueError:
                        odds_val = 1.0

                    stake = 1.0
                    pnl = (stake * odds_val - stake) if result == "WON" else -stake

                    if not is_kombi:
                        legs_total = 1
                        legs_won = 1 if result == "WON" else 0

                    settled_results.append({
                        "match": match,
                        "pick": pick,
                        "odds": odds,
                        "odds_val": odds_val,
                        "stake": stake,
                        "pnl": pnl,
                        "result": result,
                        "status": result,
                        "date": date_str,
                        "is_kombi": is_kombi,
                        "legs_won": legs_won,
                        "legs_total": legs_total,
                        "details": details_lines,
                        "sport": "NFL"
                    })
                else:
                    remaining_pending.append(bet)
            else:
                remaining_pending.append(bet)
        except Exception as e:
            print(f"Fehler bei NFL-Settlement für {match}: {e}")
            remaining_pending.append(bet)

    save_pending(remaining_pending)

    if settled_results:
        save_to_history(settled_results)

        singles = [b for b in settled_results if not b["is_kombi"]]
        kombis = [b for b in settled_results if b["is_kombi"]]

        singles_won = sum(1 for b in singles if b["result"] == "WON")
        kombis_won = sum(1 for b in kombis if b["result"] == "WON")

        total_staked = sum(b["stake"] for b in settled_results)
        total_pnl = sum(b["pnl"] for b in settled_results)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        pnl_sign = "+" if total_pnl >= 0 else ""
        profit_color = "🟢" if total_pnl >= 0 else "🔴"

        kombi_legs_won = sum(b["legs_won"] for b in kombis)
        kombi_legs_total = sum(b["legs_total"] for b in kombis)

        total_picks_count = len(singles) + kombi_legs_total
        total_picks_won = singles_won + kombi_legs_won
        overall_accuracy = (total_picks_won / total_picks_count * 100) if total_picks_count > 0 else 0

        lines = [
            "🏁 <b>JARVIS NFL — TAGESABSCHLUSS & BILANZ</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>ERGEBNISSE:</b>\n"
        ]

        for b in settled_results:
            icon = "✅" if b["result"] == "WON" else "❌"
            pnl_str = f"+{b['pnl']:.2f}u" if b["pnl"] >= 0 else f"{b['pnl']:.2f}u"

            if b["is_kombi"]:
                lines.append(f"{icon} <b>Kombi: {b['pick']}</b> (<code>@{b['odds']}</code>)")
                lines.append(f"• <b>Status:</b> {b['result']} (<code>{pnl_str}</code>)")
                lines.append(f"• <b>Beine getroffen:</b> {b['legs_won']}/{b['legs_total']}")
                for d in b.get("details", []):
                    lines.append(f"  {d}")
            else:
                lines.append(f"{icon} <b>{b['pick']}</b> (<code>@{b['odds']}</code>)")
                lines.append(f"• <b>Match:</b> {b['match']}")
                lines.append(f"• <b>Status:</b> {b['result']} (<code>{pnl_str}</code>)")
                for d in b.get("details", []):
                    lines.append(f"• <i>{d}</i>")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📊 <b>BILANZ & STATISTIK</b>")
        if singles:
            s_pnl = sum(b["pnl"] for b in singles)
            s_sign = "+" if s_pnl >= 0 else ""
            lines.append(f"• <b>Singles:</b> {singles_won}/{len(singles)} | {s_sign}{s_pnl:.2f}u")
        if kombis:
            k_pnl = sum(b["pnl"] for b in kombis)
            k_sign = "+" if k_pnl >= 0 else ""
            lines.append(f"• <b>Kombis:</b> {kombis_won}/{len(kombis)} | {k_sign}{k_pnl:.2f}u")

        lines.append(f"• <b>Trefferquote:</b> {total_picks_won}/{total_picks_count} ({overall_accuracy:.1f}%)")
        lines.append(f"• {profit_color} <b>Netto-Ertrag:</b> <b>{pnl_sign}{total_pnl:.2f} Units</b>")
        lines.append(f"• <b>ROI:</b> <b>{pnl_sign}{roi:.1f}%</b>")
        lines.append("\n📁 <i>Alle Tickets wurden in nfl_history.json archiviert.</i>")

        send_telegram("\n".join(lines).strip())
        print("NFL-Settlement erfolgreich gesendet.")

# ==========================================
# 2. ODDS API & PICKS GENERIERUNG
# ==========================================
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
            return "\n".join(events[:40])
    except Exception as e:
        print(f"Fehler bei NFL Odds: {e}")
    return ""

def run_nfl_intel():
    odds_data = fetch_nfl_odds()
    if not odds_data:
        print("Keine NFL-Spiele im Zeitfenster gefunden.")
        return

    now_dt = datetime.now(LOCAL_TZ)
    today_str = now_dt.strftime("%d.%m.%Y")
    today_iso = now_dt.strftime("%Y-%m-%d")
    current_year = now_dt.strftime("%Y")

    prompt = f"""
Du bist 'JARVIS NFL QUANT ARCHITECT'.
Erstelle für heute ({today_str}, Saison: {current_year}) das NFL-Value-Dossier.

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
2. Injury- & Weather-Check via Google Search (QB-Status, Wind/Regen bei Freiluft-Stadien, Key-Defenders Out).
3. Bei Player Props: Nur Starter (Passing Yards, Rushing Yards, Anytime Touchdown).

EXAKTES HTML-AUSGABEFORMAT:
🏈 <b>JARVIS NFL — TAGESEMPFEHLUNGEN ({today_str})</b>
━━━━━━━━━━━━━━━━━━━━
📋 <b>WETTSCHEINE AUF EINEN BLICK:</b>

⭐ <b>POTD (<code>1.50u</code> | <code>@[Quote]</code>)</b>
• <b>[Heim] vs. [Gast]</b> ➔ <i>[Spread / Total / ML]</i>

🔥 <b>QUANT VALUE ACCA (<code>1.00u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Heim] vs. [Gast] ➔ <i>[Tipp 1]</i>
• [Heim] vs. [Gast] ➔ <i>[Tipp 2]</i>

🎯 <b>TOTALS SPOTLIGHT (<code>0.75u</code> | <code>@[Quote]</code>)</b>
• <b>[Heim] vs. [Gast]</b> ➔ <i>[Over/Under Punkte]</i>

👟 <b>PLAYER PROP SPOTLIGHT (<code>0.75u</code> | <code>@[Quote]</code>)</b>
• [Spieler] ([Team]) ➔ <i>[Anytime TD / Rush/Rec Yards]</i>

━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>

🔎 <b>POTD: [Heim] vs. [Gast]</b>
• <b>Edge:</b> [EPA/Play Vorteil, Key-Matchup oder Fair-Quote]
• <b>Logik:</b> [Maximal 2 Sätze zu Offense/Defense EPA, O-Line vs D-Line Pressure Rate]

🔎 <b>Acca & Spotlights Begründung:</b>
• [Pick 1]: [1-2 Sätze Begründung]
• [Totals / Prop]: [1-2 Sätze Begründung]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NFL",
    "category": "PICK OF THE DAY",
    "pick": "Team A -3.5",
    "odds": "1.90",
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "Team C vs Team D / Team E vs Team F",
    "sport": "NFL",
    "category": "QUANT VALUE ACCA",
    "pick": "Team C ML + Team E Over 44.5",
    "odds": "2.75",
    "date": "{today_iso}",
    "is_kombi": true
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
                        pending.extend(new_picks)
                        save_pending(pending)
                        print(f"{len(new_picks)} NFL-Picks in {PENDING_FILE} gesichert.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der NFL-Picks: {je}")

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
# 3. HAUPTSTEUERUNG
# ==========================================
def main():
    now_berlin = datetime.now(LOCAL_TZ)
    current_hour = now_berlin.hour

    print(f"=== JARVIS NFL ENGINE START [{now_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}] ===")

    # Flag: Reiner Settlement-Lauf per Parameter
    settle_only = "--settle-only" in sys.argv

    # 1. Abrechnung läuft immer
    settle_pending_bets()

    if settle_only:
        print("Reiner Abrechnungslauf (--settle-only). Keine Dossier-Erstellung.")
        return

    # 2. Picks nach 15:00 Uhr MEZ an Spieltagen generieren
    if current_hour >= 15:
        print(f"Spiele-Fenster aktiv ({current_hour} Uhr MEZ): Generiere neues NFL-Dossier...")
        run_nfl_intel()
    else:
        print(f"Morgen-Fenster aktiv ({current_hour} Uhr MEZ): Nur Abrechnung ausgeführt. Picks folgen nachmittags.")

if __name__ == "__main__":
    main()
