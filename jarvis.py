import os
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

# --- API Keys & Credentials ---
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LOCAL_TZ = ZoneInfo("Europe/Berlin")

# --- Vollständiges Portfolio (Fußball, Europapokale, US-Profi- & College-Sport) ---
TARGET_LEAGUES = [
    # Europäischer Spitzenfußball (UEFA)
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",

    # Nationale Top-Ligen & Pokale
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_austria_bundesliga",
    "soccer_epl",
    "soccer_efl_champ",            # Korrigierter Key für die englische Championship
    "soccer_england_efl_cup",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",

    # US-Sportarten & College-Ligen
    "americanfootball_nfl",
    "americanfootball_ncaaf",
    "basketball_nba",
    "basketball_ncaab",
    "icehockey_nhl"
]

def fetch_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=28)

    print(f"Starte Spielabruf ab {now_utc.isoformat()} bis {cutoff.isoformat()}...")

    for sport in TARGET_LEAGUES:
        url_odds = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        try:
            res_odds = requests.get(url_odds, params=params, timeout=15)
        except requests.RequestException as e:
            print(f"Netzwerkfehler bei {sport}: {e}")
            continue

        if res_odds.status_code != 200:
            print(f"Fehler bei {sport}: Status {res_odds.status_code} - {res_odds.text}")
            continue

        data = res_odds.json()
        sport_count = 0
        for match in data:
            commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            if now_utc <= commence_utc <= cutoff:
                bookies = match.get("bookmakers", [])
                if not bookies:
                    continue

                time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M Uhr")
                details = []
                for m in bookies[0].get("markets", []):
                    m_key = m.get("key")
                    if m_key == "h2h":
                        details.append("H2H: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                    elif m_key == "totals":
                        details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))

                line = f"[{match['sport_title']}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
                matches_summary.append(line)
                sport_count += 1

        print(f"Liga {sport}: {sport_count} Spiele gefunden.")

    print(f"Gesamtanzahl gefundener Spiele: {len(matches_summary)}")
    return "\n".join(matches_summary[:200])

def analyze_with_jarvis(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = """
Du bist 'JARVIS', KI-Sportwettenanalyst. Hier sind die anstehenden realen Partien aus der Buchmacher-API mit Quoten und lokaler Zeit:
""" + matches_text + """

STRIKTE REGELN (ABSOLUTE PRIORITÄT):
1. **NUR DIESE SPIELE:** Wähle AUSSCHLIESSLICH Partien aus der obigen Liste aus! Erfinde NIEMALS eigene Spielpaarungen und nimm keine Spiele auf, die oben nicht existieren.
2. **Recherche:** Nutze die Google-Suche aktiv, um für die obigen Teams Ausfälle, Form, Matchups sowie Totals (Over/Under Linien) und Player-Props zu ermitteln.
3. **HYBRID-KOMBINATION:** Jede Kombi (Double, 3er, 4er) MUSS intern aus verschiedenen Sportarten UND verschiedenen Wettmärkten bestehen (z.B. Fußball 1X2/Doppelte Chance/Totals + NBA/NHL/NFL Over/Under, Spreads oder Tore/Props).
4. **Quoten-Disziplin:** Einzelquoten solide zwischen 1.30 und 1.75.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>Guten Tag, Sir. Hier ist Ihr optimiertes Sportwetten-Dossier:</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. DAS HYBRID-DOUBLE (2er-Kombi)</b> (Zielquote 1.80 - 2.40)
- <b>[Liga] Team A vs. Team B (Datum um Uhrzeit)</b>
  Tipp: <b>[Wette]</b> | Quote: <b>[Quote]</b>
  <i>Fakten:</i> [1-2 präzise Sätze]
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. DIE CROSS-SPORT 3er-KOMBI</b> (Zielquote 2.80 - 4.50)
[Gleicher Aufbau mit 3 Picks]
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. DIE HIGH-VALUE 4er-KOMBI</b> (Zielquote 4.50 - 8.00)
[Gleicher Aufbau mit 4 Picks]
<b>Gesamtquote: [Quote]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. PLAYER-PROPS SPECIAL (Solo)</b>
- <b>[Liga] Spielername (Team) – [Wette] (Datum um Uhrzeit)</b>
  Indikative Quote: <b>[Quote]</b>
  <i>Matchup-Analyse:</i> [1-2 Sätze]

<i>Protokoll abgeschlossen. Möge die mathematische Varianz heute zu Ihren Gunsten ausfallen, Sir.</i>
"""
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2
    )
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=config
    )
    return response.text

def send_telegram_message(text):
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

    for chunk in chunks:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=10)

if __name__ == "__main__":
    matches = fetch_matches()
    if not matches:
        send_telegram_message("ℹ️ <b>Jarvis System-Status:</b> Keine passenden Spiele im 28-Stunden-Fenster gefunden.")
    else:
        analysis = analyze_with_jarvis(matches)
        send_telegram_message(analysis)
