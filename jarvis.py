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
    Sendet den Report an Telegram. Falls die Nachricht doch geteilt werden muss,
    wird die message_id des LETZTEN Teils zurueckgegeben, damit der Live-Tracker
    immer am Ende der Kette editiert und keine doppelten Bloecke erzeugt.
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

    last_message_id = None
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

        try:
            last_message_id = res.json().get("result", {}).get("message_id")
        except Exception:
            pass

    return last_message_id

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

STRIKTE LÄNGEN- UND FORMATVORGABE (EXTREM WICHTIG):
- Der GESAMTE Text vor '---JSON_TRACKING---' darf maximal 3.200 Zeichen umfassen, damit er ungeteilt in eine einzige Telegram-Nachricht passt!
- Halte die 'Logik:' und 'Edge:' Abschnitte extrem präzise und knackig (maximal 2 bis 3 Sätze pro Ticket).
- Jede Aufzählung MUSS direkt mit '• ' (Unicode Bullet) OHNE Leerzeile beginnen.
- Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...'.
- Trennlinien exakt: '━━━━━━━━━━━━━━━━━━━━'.

⛔ STRIKTE FORM-, QUALITÄTS- UND VETO-REGELN (EXTREM WICHTIG):
1. KEINE KRISENTEAMS ALS FAVORIT / SIEG / DNB:
   - Teams, die sich in einer akuten Form- oder Trainerkrise befinden, seit 3+ Pflichtspielen sieglos sind oder weniger als 2 der letzten 5 Pflichtspiele gewonnen haben (z. B. kriselnde Großklubs wie Manchester United), sind STRIKT GESPERRT für:
     ➔ Sieg-Wetten (Home/Away Win)
     ➔ Draw No Bet (DNB)
     ➔ Doppelte Chance (1X / X2)
   - Renommee oder angeblicher 'Heimvorteil/Stadion-Mythos' wiegen sportliche Verunsicherung NICHT auf. Schönholzen von schwachen Teams ist streng untersagt!
   - Bei solchen Teams sind maximal Tore-Gegentore-Märkte (z.B. BTTS Ja / Über-Tore gegen ihre anfällige Abwehr) erlaubt – andernfalls wird die Partie komplett ignoriert.
2. VERPFLICHTENDER FORM-CHECK VIA GOOGLE SEARCH:
   - Nutze Google Search, um die aktuelle Form der letzten 3 bis 5 Pflichtspiele beider Teams abzugleichen. Wähle nur Teams für Sieg/DNB, die nachweislich ein stabiles Momentum und funktionierende Abläufe haben.
3. HARTER ROSTER-CHECK BEI SPIELER-PROPS:
   - Wähle NUR Spieler aus, die im Jahr {current_year} offiziell beim jeweiligen Team unter Vertrag stehen und voraussichtlich in der Startelf stehen.
   - Nutze Google Search zur Absicherung von Sperren/Verletzungen. Bei Unsicherheit das Player-Prop-Ticket weglassen!
4. KEINE UNDER BEI SPIELERN: Nur Over-Linien (z.B. Over 0.5 Torschüsse / 1+ SoT). Keine Under-Props!

TICKET-ARCHITEKTUR (OHNE ZWANG):
- ⭐ SOCCER PICK OF THE DAY (Single Bet): Bester Einzeltipp des Tages mit größtem mathematischem Edge und klarer Formkurve.
- 🔒 CONSERVATIVE 2-LEG BANKER: Exakt 2 Beine. Gesamtquote ~1.70 - 2.15.
- ⚖️ BALANCED VALUE ACCA: Exakt 3 Beine. Gesamtquote ~2.50 - 4.00.
- ⚡ HYBRID QUANT MULTI: 2 bis 4 Beine mit Markt-Mix (Sieg, BTTS, Über 2.5).
- ⚽ GOALS & BTTS VALUE ACCA: 2 bis 3 Beine rein aus Tor-Märkten.
- 👟 PLAYER PROPS (Single oder Multi-Acca): 1 bis 2 Spieler (1+ Schuss aufs Tor).

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
🔍 <b>Edge:</b> [Maximal 2 prägnante Sätze zur Kante]

━━━━━━━━━━━━━━━━━━━━
🔒 <b>CONSERVATIVE 2-LEG BANKER</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 1.0 - 1.5 Units
🔍 <b>Logik:</b> [Maximal 2 Sätze Begründung]

━━━━━━━━━━━━━━━━━━━━
⚖️ <b>BALANCED VALUE ACCA (3-er Kombi)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 3]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.75 - 1.0 Units
🔍 <b>Logik:</b> [Maximal 2 Sätze Begründung]

━━━━━━━━━━━━━━━━━━━━
⚡ <b>HYBRID QUANT MULTI (Markt-Mix)</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Markt & Tipp]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Markt & Tipp]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Markt & Tipp]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.5 - 0.75 Units
🔍 <b>Logik:</b> [Maximal 2 Sätze Begründung]

━━━━━━━━━━━━━━━━━━━━
⚽ <b>GOALS & BTTS VALUE ACCA</b>
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tore-Tipp]</b> @ [Quote]
- [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tore-Tipp]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.75 Units
🔍 <b>Logik:</b> [Maximal 2 Sätze Begründung]

━━━━━━━━━━━━━━━━━━━━
👟 <b>PLAYER PROP SPOTLIGHT / MULTI-TICKET</b>
- [Uhrzeit] Uhr | [Spieler 1] ([Team]) ➔ <b>[Tipp: 1+ Torschuss]</b> @ [Quote]
- [Uhrzeit] Uhr | [Spieler 2] ([Team]) ➔ <b>[Tipp: 1+ Torschuss]</b> @ [Quote]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b> | 💰 <b>Einsatz:</b> 0.5 - 0.75 Units
🔍 <b>Edge:</b> [Maximal 2 Sätze Begründung]

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
    host = "generativelanguage.googleapis.com"
    path = "v1beta/models/gemini-3.8-flash:generateContent"
    api_url = f"https://{host}/{path}?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(api_url, json=payload, timeout=90)
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
                        print(f"[Tracking] Fehler beim Parsen des JSON-Blocks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                
                # Report absenden und ID der letzten Teilnachricht holen
                msg_id = send_telegram(report)

                # Nachricht und ID im Tracking-JSON verankern
                if tracking_data:
                    if msg_id:
                        tracking_data["message_id"] = int(msg_id)
                    tracking_data["original_text"] = report
                    try:
                        with open(PENDING_FILE, "w", encoding="utf-8") as f:
                            json.dump(tracking_data, f, ensure_ascii=False, indent=2)
                        print(f"Soccer-Picks mit message_id ({msg_id}) in {PENDING_FILE} gesichert.")
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
