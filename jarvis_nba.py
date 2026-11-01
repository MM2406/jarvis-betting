import os
import sys
import json
import time
import requests
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

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
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_nba.json"

# ==========================================
# STATE & TELEGRAM HILFSFUNKTIONEN
# ==========================================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
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
        except ValueError:
            print(f"Ungueltige Thread-ID fuer NBA: {TELEGRAM_THREAD_ID}")

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

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

# ==========================================
# 1. MORGEN-SETTLEMENT (AUSWERTUNG)
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
        odds = bet.get("odds", "-")
        date_str = bet.get("date", "")

        prompt = f"""
Du bist ein Sport-Abrechnungssystem für die NBA.
Ermittle via Google Search das offizielle Endergebnis des folgenden Spiels:
- Spiel: {match}
- Datum: {date_str}
- Wette: {pick}

SUCH-ANWEISUNG:
Suche nach "{match} nba box score final" oder "{match} espn final".

AUFGABE:
1. Prüfe, ob das Spiel offiziell beendet ist (FINAL).
2. Falls beendet: Ermittle den Endstand (z.B. '112:108') und bewerte, ob die Wette '{pick}' GEWONNEN (WON) oder VERLOREN (LOST) ist.
3. Falls das Spiel noch nicht beendet, verschoben oder noch nicht gespielt ist, antworte mit PENDING.

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder PENDING
SCORE: Endergebnis (z.B. 115:102)
RESULT: WON oder LOST oder PENDING
DETAILS: Ein kurzer Satz zum Ergebnis (z.B. 'Celtics gewinnen mit 12 Punkten Vorsprung.')
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

                if status == "FINISHED" and result in ["WON", "LOST"]:
                    icon = "✅" if result == "WON" else "❌"
                    settled_results.append({
                        "match": match,
                        "pick": pick,
                        "odds": odds,
                        "result": result,
                        "icon": icon,
                        "score": score,
                        "details": details
                    })
                else:
                    remaining_pending.append(bet)
            else:
                remaining_pending.append(bet)
        except Exception as e:
            print(f"Fehler bei Abrechnung für {match}: {e}")
            remaining_pending.append(bet)

    save_pending(remaining_pending)

    if settled_results:
        msg = "🏀 <b>JARVIS NBA • RECAP & ABRECHNUNG</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        for r in settled_results:
            msg += f"{r['icon']} <b>Tipp:</b> {r['pick']} @ {r['odds']}\n"
            msg += f"• <b>Match:</b> {r['match']}\n"
            msg += f"• <b>Ergebnis:</b> {r['score']} ({r['result']})\n"
            if r['details']:
                msg += f"• <i>{r['details']}</i>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━\n"

        send_telegram(msg)
        print("Abrechnungs-Nachricht an Telegram gesendet.")

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
Du bist 'JARVIS NBA QUANT' – Spezialist für quantitative NBA-Modellierung, Possession-Analytics und Quoten-Diskrepanzen.
Erstelle für heute ({today_str}) das NBA-Dossier.

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN:
{odds_data}

RICHTLINIEN & MÄRKTE:
- Wähle ausschließlich Partien aus der obigen Liste.
- Analysiere Pace, Offensive/Defensive Ratings, Net-Rating Edge, Rest Advantage (Back-to-Back) und Lineup-News via Google Search.
- DYNAMISCHE ACCA: Begrenze dich beim Kombi-Ticket NICHT auf 2 Spiele. Kombiniere 2 bis 4 Spiele mit klarem mathematischem Vorteil (+EV).
- BUCHMACHER-ALTERNATIVE: Gib für jeden Spread/Total-Pick immer eine Standard-Linie für europäische Bookies an (z.B. bet365/Tipico).
- VALUE-GRENZE: Weise für jeden Single-Tipp und für die Kombi eine Mindestquote aus ('Spielbar bis @ X.XX').
- UNITS:
  * Pick of the Day: 1.0 bis 2.0 Units
  * Value Acca: 0.5 bis 1.0 Units
  * Totals Spotlight: 0.5 bis 1.0 Units
  * Player Prop: 0.5 bis 1.0 Units

FORMATIERUNGS-REGELN FÜR TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzählung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🏀 <b>JARVIS NBA INTEL DOSSIER</b>
<i>Quantitative Match-Modelle • Net-Rating Edge • Value-Picks</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>NBA PICK OF THE DAY (Single Bet)</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Haupt-Pick:</b> <b>[Spread / Total / Moneyline]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [1.0 - 2.0] Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [Pace-Projektion, Matchup-Vorteile, Rest Advantage, Schussqualität]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA ([Anzahl]-er Kombi)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 3]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Kombi-Logik:</b> [Warum diese Kombination mathematisch korreliert oder unabhängig starken Value bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>PACE &amp; TOTALS SPOTLIGHT</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Over/Under / Team-Total]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [Possessions-Projektion, Transition-Defense, Shooting-Splits]

━━━━━━━━━━━━━━━━━━━━
👟 <b>NBA PLAYER PROP SPOTLIGHT</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Spielername: Punkte / Rebounds / Assists / 3PT Made]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative Linie / Markt-Fallback] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [Usage-Rate, Matchup gegen gegnerische Defense-Position, Minuten-Projektion]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NBA",
    "pick": "Team A -3.5",
    "odds": "1.90",
    "date": "{today_iso}"
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
                        print(f"{len(new_picks)} NBA-Picks getrackt.")
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

    # 1. Abrechnung läuft IMMER
    settle_pending_bets()

    # 2. Picks nur ab 16:00 Uhr MEZ generieren
    if current_hour >= 16:
        print(f"Abend-Fenster aktiv ({current_hour} Uhr MEZ): Starte Quotenabfrage & Dossier-Erstellung...")
        run_nba_intel()
    else:
        print(f"Morgen-Fenster aktiv ({current_hour} Uhr MEZ): Nur Abrechnung ausgeführt. Picks folgen um 18:00 Uhr MEZ.")

if __name__ == "__main__":
    main()
