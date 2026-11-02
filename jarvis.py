import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

try:
    from telegram_sender import send_to_telegram
except ImportError:
    send_to_telegram = None

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_soccer.json"

SOCCER_LEAGUES = [
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_usa_mls"
]

def send_telegram(text):
    """
    Sendet den Report an Telegram und gibt die message_id zurueck,
    damit der Live-Tracker spaeter Zwischenstaende hineineditieren kann.
    """
    if send_to_telegram:
        return send_to_telegram(text, thread_env_var="TELEGRAM_THREAD_SOCCER")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] FEHLER: Credentials fehlen.")
        return None

    if not TELEGRAM_THREAD_ID:
        print("[Telegram] ABBRUCH: Keine Soccer Thread-ID vorhanden. Senden in Hauptchat blockiert.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 3800
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

    first_message_id = None
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "message_thread_id": int(TELEGRAM_THREAD_ID)
        }
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code != 200:
                print(f"[Telegram] Fehler: {res.text}")
                continue

        # message_id der ersten/Haupt-Nachricht festhalten
        if not first_message_id:
            try:
                first_message_id = res.json().get("result", {}).get("message_id")
            except Exception:
                pass

    return first_message_id

def fetch_soccer_odds():
    all_events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=14)

    for league in SOCCER_LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                matches = res.json()
                for match in matches:
                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue
                        
                        odds_summary = []
                        for m in bookies[0].get("markets", []):
                            outcomes = [f"{o['name']}: {o['price']}" for o in m.get("outcomes", [])]
                            odds_summary.append(f"{m.get('key')}: {', '.join(outcomes)}")

                        line = f"[{league.replace('soccer_', '').upper()}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(odds_summary)}"
                        all_events.append(line)
        except Exception as e:
            print(f"Fehler bei Liga {league}: {e}")

    print(f"Gefundene Soccer-Partien: {len(all_events)}")
    return "\n".join(all_events[:65])

def run_jarvis_soccer():
    odds_data = fetch_soccer_odds()
    if not odds_data:
        print("Keine relevanten Soccer-Partien im aktuellen Zeitfenster gefunden.")
        return

    now_dt = datetime.now(LOCAL_TZ)
    today_str = now_dt.strftime("%d.%m.%Y")
    today_iso = now_dt.strftime("%Y-%m-%d")
    current_year = now_dt.strftime("%Y")
    edition_label = "MITTAGS-EDITION" if now_dt.hour < 15 else "ABEND-EDITION"

    prompt = f"""
Du bist 'JARVIS SOCCER QUANT ARCHITECT'.
HEUTIGES DATUM: {today_str} (Aktuelles Jahr: {current_year}).
Erstelle für heute die {edition_label}.

VERFÜGBARE PARTIEN & REAL-QUOTEN AUS DER API:
{odds_data}

STRIKTE GROUNDING- UND VERIFIKATIONS-REGELN (VERPFLICHTEND!):
1. VERBOT VON HISTORISCHEN/HALLUZINIERTEN MATCHES: Verwende AUSSCHLIESSLICH Spiele und Teams, die exakt in der obigen Liste stehen!
2. HARTER ROSTER- & KADER-CHECK BEI SPIELER-PROPS:
   - Du darfst NUR Spieler auswählen, die im aktuellen Jahr {current_year} zweifelsfrei und offiziell bei einem der oben aufgeführten Teams spielen!
   - Führe zwingend eine Google Search durch, um den AKTUELLEN VEREIN und die VORAUSSICHTLICHE AUFSTELLUNG des Spielers zu verifizieren.
   - Wenn ein Spieler transferiert wurde, verletzt ausfällt oder nicht im heutigen Kader steht, ist er STRIKT VERBOTEN.
   - KEIN Raten aus historischem Wissen! Wenn du nicht zu 100% via Websuche belegen kannst, dass der Spieler heute im Kader seines aktuellen Vereins steht, lasse das Player-Prop-Ticket komplett weg.
3. KEINE UNDER BEI SPIELERN: Bei Spielerwetten nur Over-Linien (z.B. Over 0.5 Torschüsse / 1+ Torschuss, Over 1.5 Schüsse, Anytime Goal, Scorerpunkt). Keine Under-Props!
4. RECHERCHE: Nutze Google Search für aktuelle Startelf-Prognosen, Ausfälle, xG und Spieler-Torschussstatistiken.

TICKET-ARCHITEKTUR (OHNE ZWANG! Wenn kein Value vorliegt, lasse das jeweilige Ticket weg):
- ⭐ SOCCER PICK OF THE DAY (Single Bet): Der beste Einzeltipp des Tages mit größtem mathematischem Edge.
- 🔒 CONSERVATIVE 2-LEG BANKER: Exakt 2 Beine. Gesamtquote ~1.70 - 2.15. Fokus: Maximale Stabilität (z.B. ML Favorit, 1X, Über 1.5 Tore).
- ⚖️ BALANCED VALUE ACCA: Exakt 3 Beine. Gesamtquote ~2.50 - 4.00.
- ⚡ HYBRID QUANT MULTI: 2 bis 4 Beine mit Markt-Mix (z.B. Spiel A Sieg + Spiel B BTTS + Spiel C Über 2.5), wo es taktisch und rechnerisch korreliert.
- ⚽ GOALS & BTTS VALUE ACCA: 2 bis 3 Beine rein aus Tor-Märkten (Über 2.5, BTTS Ja).
- 👟 PLAYER PROPS (Single oder Multi-Acca):
  * Wähle 1 bis 3 Spieler aus den HEUTIGEN, oben gelisteten Partien (Torschüsse aufs Tor / SoT, Tore, Tor+Vorlage).
  * Vor jedem Spieler-Tipp muss der aktuelle Verein des Spielers via Google Search verifiziert sein!
  * Wenn mehrere starke Spieler-Picks vorhanden sind, kombiniere sie zu einer 2er- oder 3er-Player-Prop-Kombi (z.B. Spieler A 1+ SoT & Spieler B 1+ SoT @ ~2.10) ODER stelle sie als starke Einzelpicks dar!
- 💣 HIGH-YIELD LOTTO / RISIKO ACCA (Optional): 4 bis 5 Beine, Quote 5.00+ bis 12.00 (Einsatz 0.25 - 0.5 Units). Nur aufführen, wenn Spitzen-Value vorhanden ist!

TELEGRAM-FORMATIERUNG:
- Keine doppelten Leerzeilen.
- Jede Aufzählung MUSS direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch beginnen!
- Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Trennlinien exakt: '━━━━━━━━━━━━━━━━━━━━'

REPORT-HTML:
⚽ <b>JARVIS SOCCER INTEL • {edition_label}</b>
<i>xG-Modelle • Poisson-Projektionen • Value-Kombis</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>SOCCER PICK OF THE DAY (Single Bet)</b>
- <b>Match:</b> [Uhrzeit] Uhr | [Heim] vs. [Gast] ([Liga])
➔ <b>Haupt-Pick:</b> <b>[Tipp]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> 1.5 - 2.0 Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [npxG-Differenz, Formkurve, Matchup-Analyse]

━━━━━━━━━━━━━━━━━━━━
🔒 <b>CONSERVATIVE 2-LEG BANKER</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 1.0 - 1.5 Units
🔍 <b>Logik:</b> [Warum diese 2 Säulen maximale Stabilität bieten]

━━━━━━━━━━━━━━━━━━━━
⚖️ <b>BALANCED VALUE ACCA (3-er Kombi)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 3]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.75 - 1.0 Units
🔍 <b>Logik:</b> [Erwartungswert & Synergie]

━━━━━━━━━━━━━━━━━━━━
⚡ <b>HYBRID QUANT MULTI (Markt-Mix)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Markt & Tipp]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Markt & Tipp]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Markt & Tipp]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.5 - 0.75 Units
🔍 <b>Logik:</b> [Synergie aus Sieg, Toren oder Handicaps]

━━━━━━━━━━━━━━━━━━━━
⚽ <b>GOALS & BTTS VALUE ACCA</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tore-Tipp]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tore-Tipp]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.75 Units
🔍 <b>Logik:</b> [Total xG, Tempo, Offensiv-Drang]

━━━━━━━━━━━━━━━━━━━━
👟 <b>PLAYER PROP SPOTLIGHT / MULTI-TICKET</b>
- [Uhrzeit] Uhr | [Spieler 1] ([Team]) ➔ <b>[Tipp: z.B. 1+ Torschuss / Tor]</b> @ [Quote]
- [Uhrzeit] Uhr | [Spieler 2] ([Team]) ➔ <b>[Tipp: z.B. 1+ Torschuss / Tor]</b> @ [Quote]
📈 <b>Gesamtquote (falls Kombi):</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.5 - 0.75 Units
🔍 <b>Edge:</b> [Schussfrequenz pro 90 Min, Strafraumaktionen, Gegner-Zulassung]

━━━━━━━━━━━━━━━━━━━━
💣 <b>HIGH-YIELD VALUE ACCA (Risiko-Kombi)</b>
[Nur aufführen, falls heute echter Value existiert, sonst Block ganz weglassen!]

---JSON_TRACKING---
{{
  "date": "{today_iso}",
  "potd": {{
    "match": "Heim vs Gast",
    "pick": "Tipp",
    "odds": 1.85
  }},
  "tickets": [
    {{
      "ticket_name": "CONSERVATIVE 2-LEG BANKER",
      "odds": 1.95,
      "picks": [
        {{"match": "Team A vs Team B", "pick": "Team A Sieg", "odds": 1.40}},
        {{"match": "Team C vs Team D", "pick": "Über 1.5 Tore", "odds": 1.39}}
      ]
    }},
    {{
      "ticket_name": "BALANCED VALUE ACCA",
      "odds": 3.20,
      "picks": [
        {{"match": "Team E vs Team F", "pick": "Team E DNB", "odds": 1.45}},
        {{"match": "Team G vs Team H", "pick": "Team G Sieg", "odds": 1.50}},
        {{"match": "Team I vs Team J", "pick": "Über 2.5 Tore", "odds": 1.47}}
      ]
    }},
    {{
      "ticket_name": "HYBRID QUANT MULTI",
      "odds": 4.10,
      "picks": [
        {{"match": "Team K vs Team L", "pick": "Team K Sieg", "odds": 1.60}},
        {{"match": "Team M vs Team N", "pick": "BTTS Ja", "odds": 1.65}},
        {{"match": "Team O vs Team P", "pick": "Unter 3.5 Tore", "odds": 1.55}}
      ]
    }},
    {{
      "ticket_name": "GOALS & BTTS VALUE ACCA",
      "odds": 2.80,
      "picks": [
        {{"match": "Team Q vs Team R", "pick": "Über 2.5 Tore", "odds": 1.65}},
        {{"match": "Team S vs Team T", "pick": "BTTS Ja", "odds": 1.70}}
      ]
    }},
    {{
      "ticket_name": "PLAYER PROPS MULTI",
      "odds": 2.45,
      "picks": [
        {{"match": "Team U vs Team V", "player": "Spieler 1", "pick": "1+ Schuss aufs Tor", "odds": 1.55}},
        {{"match": "Team W vs Team X", "player": "Spieler 2", "pick": "1+ Schuss aufs Tor", "odds": 1.58}}
      ]
    }}
  ]
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = full_reply
                tracking_data = {}

                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        tracking_data = json.loads(json_str)
                    except Exception as je:
                        print(f"Fehler beim Parsen der Tracking-Picks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                
                # Report absenden und message_id abfangen
                msg_id = send_telegram(report)

                # Nachricht und ID im Tracking-JSON verankern
                if tracking_data:
                    if msg_id:
                        tracking_data["message_id"] = int(msg_id)
                    tracking_data["original_text"] = report
                    try:
                        with open(PENDING_FILE, "w", encoding="utf-8") as f:
                            json.dump(tracking_data, f, ensure_ascii=False, indent=2)
                        print(f"Soccer-Picks inklusive message_id ({msg_id}) in {PENDING_FILE} gespeichert.")
                    except Exception as fe:
                        print(f"Fehler beim Speichern von {PENDING_FILE}: {fe}")

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
    run_jarvis_soccer()
