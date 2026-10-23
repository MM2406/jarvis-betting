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

# Ausgewählte Kernligen: DACH, England, Top-Ligen & Europapokal
SOCCER_LEAGUES = [
    # Deutschland & Österreich
    ("soccer_germany_bundesliga", "1. Bundesliga GER"),
    ("soccer_germany_bundesliga2", "2. Bundesliga GER"),
    ("soccer_austria_bundesliga", "Admiral Bundesliga AUT"),
    # England
    ("soccer_epl", "Premier League"),
    ("soccer_efl_champ", "Championship ENG"),
    # Top-Ligen Europa
    ("soccer_spain_la_liga", "La Liga"),
    ("soccer_italy_serie_a", "Serie A"),
    ("soccer_france_ligue_one", "Ligue 1"),
    # UEFA-Wettbewerbe
    ("soccer_uefa_champs_league", "Champions League"),
    ("soccer_uefa_europa_league", "Europa League"),
    ("soccer_uefa_europa_conference_league", "Conference League")
]

def fetch_soccer_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=28)

    for sport_key, league_name in SOCCER_LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
        except requests.RequestException:
            continue

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
                        details.append("1X2: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                    elif m_key == "totals":
                        details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))

                line = f"[{league_name}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
                matches_summary.append(line)

    print(f"Fußball-Partien gefunden: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_soccer(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = """
Du bist 'JARVIS SOCCER PRO', ein datengetriebener Quantitative-Analyst für europäischen Profifußball.
Hier sind die realen anstehenden Partien inklusive Buchmacher-Quoten und Spielzeiten:
""" + matches_text + """

DEINE AUFGABE & REGELN:
1. Wähle primär aus den oben gelisteten realen Partien (Bundesliga 1 & 2, Österreich, Championship, Top-Ligen, Europacup).
   - Ergänzung: Falls am Spieltag interessante Partien der 2. Liga Österreich laufen, darfst du diese aktiv via Google-Suche für Quoten und Matchups einbinden.
2. Gib bei JEDEM Pick und bei JEDEM Torschützen-Tipp IMMER die genaue Anstoßzeit (MESZ/MEZ) an!
3. Nutze die Google-Suche aktiv für:
   - xG-Statistiken (Expected Goals) und Defensiv-Schwächen der Teams.
   - Verletzungen, Ausfälle von Stammkräften, Sperren und Rotationswarnungen.
   - Spezifische Liga-Trends (z.B. hohe Torquote in der 2. Bundesliga, Unentschieden-Häufigkeit in La Liga, Dominanz in Österreich).
4. Erstelle 3 mathematisch fundierte Kombiwetten sowie einen Torschützen/Special-Pick.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>⚽ JARVIS FOOTBALL INTEL & VALUE REPORT</b>
<i>Analysen für Bundesliga, Österreich, Championship & Top-Ligen</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. DIE BANKER-DOPPELCHANCE (2er-Kombi)</b>
<i>Hohe Trefferwahrscheinlichkeit: 1X2 Favorit, DNB oder Doppelte Chance (Quote ca. 2.10 - 2.60)</i>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [1 prägnanter Satz zu Form und Stabilität]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. GOALS & BTTS VALUE TICKET (3er-Kombi)</b>
<i>Fokus auf Tore: Über 2.5 Tore, Beide treffen (BTTS) oder Asian Totals (Quote ca. 4.00 - 6.50)</i>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Begründung über Torchancen/xG und Abwehrprobleme]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. MULTI-LEAGUE VALUE TICKET (3er-Kombi)</b>
<i>Ausgewogene 3er-Kombination aus Siegwetten / Handicaps quer durch die Ligen (Quote ca. 4.50 - 7.50)</i>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Taktischer Matchup-Vorteil]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. VALUE TORSCHÜTZE / SPECIAL PICK</b>
- <b>[Uhrzeit] Spieler (Team, Liga) vs. Gegner: [Anytime Goalscorer / Vorlage]</b> | Quote: <b>[Quote]</b>
  <i>Spotlight:</i> [Formkurve, Elfmeter-Schütze, gegnerische Anfälligkeit]

<i>Abpfiff, Sir. Volle Disziplin bei der Schein-Auswahl.</i>
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
    matches = fetch_soccer_matches()
    if not matches:
        send_telegram_message("⚽ <b>Jarvis Fußball Status:</b> Keine Spiele in den hinterlegten Ligen im aktuellen 28-Stunden-Fenster.")
    else:
        report = analyze_soccer(matches)
        send_telegram_message(report)
