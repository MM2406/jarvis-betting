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

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()
    or os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()
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
    "soccer_uefa_europa_conference_league",
    "soccer_usa_mls"
]

def send_telegram(text):
    """Sendet die Nachricht garantiert in das richtige Soccer-Topic."""
    if send_to_sport_channel:
        msg_id = send_to_sport_channel(text, sport="soccer")
        if msg_id:
            return msg_id

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
    now_dt = datetime.now(LOCAL_TZ)
    weekday = now_dt.weekday()  # 0=Mo, 4=Fr, 5=Sa, 6=So
    now_hour = now_dt.hour

    # Unter der Woche (Mo - Fr) keine Posts vor 16:00 Uhr MEZ
    if weekday < 5 and now_hour < 16:
        print(f"Wochentag-Check ({now_hour}:00 Uhr MEZ): Unter der Woche werden Dossiers erst ab 16:00 Uhr für die Abendslots generiert. Abbruch.")
        return

    odds_data = fetch_soccer_odds()
    if not odds_data:
        print("Keine relevanten Soccer-Partien im aktuellen Zeitfenster gefunden.")
        return

    today_str = now_dt.strftime("%d.%m.%Y")
    today_iso = now_dt.strftime("%Y-%m-%d")
    current_year = now_dt.strftime("%Y")
    edition_label = "TAGES-SLATE" if now_hour < 15 else "HAUPT- & ABEND-SLATE"

    prompt = f"""
Du bist 'JARVIS SOCCER QUANT ARCHITECT'.
HEUTIGES DATUM: {today_str} (Aktuelles Jahr: {current_year}).
Erstelle für heute das Value-Dossier für die Slate ({edition_label}).

VERFÜGBARE PARTIEN & REAL-QUOTEN AUS DER API:
{odds_data}

================================================================================
STRIKTE ARCHITEKTUR & LAYOUT-REGELN (PICKS FIRST):
================================================================================
1. PICKS FIRST:
   - Die spielfertigen Wettscheine (POTD, Kombis, Props) stehen ZWINGEND GANZ OBEN direkt unter dem Header!
   - Erst DANACH folgt die Trennlinie '━━━━━━━━━━━━━━━━━━━━' und der Abschnitt 'ANALYSEN & MODELL-LOGIK (DEEP DIVE)'.
2. LÄNGEN-LIMIT:
   - Der GESAMTE Text vor '---JSON_TRACKING---' darf maximal 3.400 Zeichen umfassen!
   - Keine doppelten Leerzeilen zwischen Absätzen.
3. FORMATIERUNG:
   - Quoten und Stakes immer in <code>...</code> setzen (z. B. <code>@1.85</code>, <code>1.50u</code>).
   - Trennlinie IMMER exakt 20 Zeichen: '━━━━━━━━━━━━━━━━━━━━'.
   - Begründungen im Deep Dive präzise und fundiert in maximal 2 Sätzen halten.

⛔ STRIKTE QUANT- & VETO-REGELN:
1. MINDESTQUOTE BEACHTEN:
   - KEINE Einzelquoten unter 1.35! Quoten wie 1.20 oder 1.30 sind STRIKT VERBOTEN.
   - Falls ein klarer Favorit unter 1.35 notiert, weiche auf Handicap (-1.0 / -1.5) oder Tor-Märkte aus oder ignoriere das Match.
2. KEINE KRISENTEAMS ALS FAVORIT / SIEG / DNB:
   - Teams, die sich in einer akuten Form- oder Trainerkrise befinden, seit 3+ Spielen sieglos sind oder weniger als 2 der letzten 5 Spiele gewonnen haben, sind für Sieg-Wetten STRIKT GESPERRT.
3. FORM- & ROSTER-CHECK VIA GOOGLE SEARCH:
   - Überprüfe via Google Search aktuelle Ausfälle, Rotationen und Trainerstimmen.
   - Bei Player Props: Nur Spieler wählen, die im Jahr {current_year} fix im Kader stehen und sicher starten. Nur OVER-Torschüsse (1+ Schuss aufs Tor), KEINE Under-Props!

EXAKTES HTML-AUSGABEFORMAT:
⚽ <b>JARVIS SOCCER — TAGESEMPFEHLUNGEN ({today_str})</b>
━━━━━━━━━━━━━━━━━━━━
📋 <b>WETTSCHEINE AUF EINEN BLICK:</b>

⭐ <b>POTD (<code>1.50u</code> | <code>@[Quote]</code>)</b>
• <b>[Heim] vs. [Gast]</b> ➔ <i>[Tipp]</i>

🔥 <b>CONSERVATIVE BANKER (<code>1.25u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Heim] vs. [Gast] ➔ <i>[Tipp 1]</i>
• [Heim] vs. [Gast] ➔ <i>[Tipp 2]</i>

⚖️ <b>BALANCED VALUE ACCA (<code>0.75u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Heim] vs. [Gast] ➔ <i>[Tipp 1]</i>
• [Heim] vs. [Gast] ➔ <i>[Tipp 2]</i>
• [Heim] vs. [Gast] ➔ <i>[Tipp 3]</i>

⚡ <b>HYBRID QUANT MULTI (<code>0.50u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Heim] vs. [Gast] ➔ <i>[Markt & Tipp 1]</i>
• [Heim] vs. [Gast] ➔ <i>[Markt & Tipp 2]</i>

⚽ <b>GOALS & BTTS VALUE ACCA (<code>0.75u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Heim] vs. [Gast] ➔ <i>[Tore-Tipp 1]</i>
• [Heim] vs. [Gast] ➔ <i>[Tore-Tipp 2]</i>

🎯 <b>PLAYER PROPS MULTI (<code>0.50u</code> | Gesamt: <code>@[Quote]</code>)</b>
• [Spieler 1] ([Team]) ➔ <i>1+ Schuss aufs Tor</i>
• [Spieler 2] ([Team]) ➔ <i>1+ Schuss aufs Tor</i>

━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSEN & MODELL-LOGIK (DEEP DIVE)</b>

🔎 <b>POTD: [Heim] vs. [Gast]</b>
• <b>Edge:</b> [Prozentuale Kante oder Fair-Quote]
• <b>Logik:</b> [Maximal 2 präzise Sätze zur taktischen Kante / xG]

🔎 <b>Banker & Value Begründungen:</b>
• [Team 1]: [1-2 Sätze Begründung]
• [Team 2]: [1-2 Sätze Begründung]
• [Team 3]: [1-2 Sätze Begründung]

---JSON_TRACKING---
{{
  "date": "{today_iso}",
  "potd": {{
    "match": "Heim vs. Gast",
    "pick": "Tipp",
    "odds": 1.85,
    "stake": 1.50
  }},
  "tickets": [
    {{
      "ticket_name": "CONSERVATIVE BANKER",
      "odds": 1.95,
      "stake": 1.25,
      "picks": [
        {{"match": "Team A vs. Team B", "pick": "Team A Sieg", "odds": 1.40}},
        {{"match": "Team C vs. Team D", "pick": "Über 1.5 Tore", "odds": 1.39}}
      ]
    }},
    {{
      "ticket_name": "BALANCED VALUE ACCA",
      "odds": 3.20,
      "stake": 0.75,
      "picks": [
        {{"match": "Team E vs. Team F", "pick": "Team E DNB", "odds": 1.45}},
        {{"match": "Team G vs. Team H", "pick": "Team G Sieg", "odds": 1.50}},
        {{"match": "Team I vs. Team J", "pick": "Über 2.5 Tore", "odds": 1.47}}
      ]
    }},
    {{
      "ticket_name": "HYBRID QUANT MULTI",
      "odds": 3.10,
      "stake": 0.50,
      "picks": [
        {{"match": "Team K vs. Team L", "pick": "Team K Sieg", "odds": 1.60}},
        {{"match": "Team M vs. Team N", "pick": "Unter 3.5 Tore", "odds": 1.55}}
      ]
    }},
    {{
      "ticket_name": "GOALS & BTTS VALUE ACCA",
      "odds": 2.80,
      "stake": 0.75,
      "picks": [
        {{"match": "Team Q vs. Team R", "pick": "Über 2.5 Tore", "odds": 1.65}},
        {{"match": "Team S vs. Team T", "pick": "BTTS Ja", "odds": 1.70}}
      ]
    }},
    {{
      "ticket_name": "PLAYER PROPS MULTI",
      "odds": 2.45,
      "stake": 0.50,
      "picks": [
        {{"match": "Team U vs. Team V", "player": "Spieler 1", "pick": "1+ Schuss aufs Tor", "odds": 1.55}},
        {{"match": "Team W vs. Team X", "player": "Spieler 2", "pick": "1+ Schuss aufs Tor", "odds": 1.58}}
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
