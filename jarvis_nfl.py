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

def fetch_nfl_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    # 36-Stunden-Fenster erfasst von Sonntag bis Montagmorgen alle anstehenden Partien
    cutoff = now_utc + timedelta(hours=36)

    url_odds = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }

    try:
        res = requests.get(url_odds, params=params, timeout=15)
        if res.status_code != 200:
            print(f"Fehler beim NFL-Abruf: {res.status_code} - {res.text}")
            return ""
        data = res.json()
    except requests.RequestException as e:
        print(f"Netzwerkfehler: {e}")
        return ""

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
                    details.append("ML: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                elif m_key == "spreads":
                    details.append("Spread: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                elif m_key == "totals":
                    details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))

            line = f"[NFL] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}"
            matches_summary.append(line)

    print(f"NFL-Spiele im Zeitfenster: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nfl(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = """
Du bist 'JARVIS NFL PRO', ein analytischer Experte für American Football und Sportwetten.
Hier sind die realen anstehenden NFL-Spiele mit Buchmacher-Linien und Anstoßzeiten:
""" + matches_text + """

DEINE AUFGABE & REGELN:
1. Wähle AUSSCHLIESSLICH Partien aus der obigen Liste aus.
2. Gib bei JEDEM Pick, bei JEDER Kombi und bei JEDEM Player-Prop IMMER die genaue Kickoff-Uhrzeit (MESZ/MEZ) aus den Daten an!
3. Nutze die Google-Suche aktiv für:
   - Offiziellen NFL Injury Report (Key Inactives, O-Line, Cornerback-Matchups).
   - Wetterberichte (Wind über 15-20 mph drückt Passing Yards und Totals).
   - Reale Player-Prop-Trends (Passing/Rushing/Receiving Yards, TD-Scorer).
4. Erstelle 3 differenzierte, mathematisch fundierte Kombiwetten sowie einen ATTD-Tipp.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - KEIN Markdown, keine Sterne, keine Raute):
<b>🏈 JARVIS NFL GAMEPLAN & VALUE REPORT</b>
<i>Analysen und Kombi-Empfehlungen für den Spieltag</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. GAME-DAY DOUBLE (2er-Kombi)</b>
<i>Favoriten & Key-Number Spreads mit hoher Trefferwahrscheinlichkeit (Quote ca. 2.20 - 2.80)</i>
- <b>[Uhrzeit] Team A vs. Team B</b> -> Pick: <b>[Spread oder ML]</b> (Quote)
- <b>[Uhrzeit] Team C vs. Team D</b> -> Pick: <b>[Spread oder Over/Under]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [1 prägnanter Satz zum Vorteil]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. THE MAIN SLATE VALUE TICKET (3er-Kombi)</b>
<i>Attraktive 3er-Kombination aus Totals und Spreads (Quote ca. 4.00 - 6.50)</i>
- <b>[Uhrzeit] Matchup 1</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Matchup 2</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] Matchup 3</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Matchup- und Taktik-Begründung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. WEAPONS & YARDS KOMBI (Player-Props 2er-Ticket)</b>
<i>Reine Spieler-Wetten (Rushing/Receiving Yards oder Passing TDs - Quote ca. 2.80 - 4.50)</i>
- <b>[Uhrzeit] Spieler A (Team vs. Gegner, Pos): [z.B. Over 65.5 Rushing Yards]</b> (Quote)
- <b>[Uhrzeit] Spieler B (Team vs. Gegner, Pos): [z.B. Over 5.5 Receptions / Over 1.5 Passing TDs]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Red-Zone-Volume, Defense-Schwächen]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. ANYTIME TOUCHDOWN (ATTD) VALUE PICK</b>
- <b>[Uhrzeit] Spieler (Team vs. Gegner): Anytime Touchdown Scorer</b> | Quote: <b>[Quote]</b>
  <i>Begründung:</i> [Goal-Line-Rolle, Snap-Count, Matchup-Vorteil]

<i>Touchdown, Sir. Mögen die Linien zu unseren Gunsten ausschlagen.</i>
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
    matches = fetch_nfl_matches()
    if not matches:
        send_telegram_message("🏈 <b>Jarvis NFL Status:</b> Aktuell stehen im Zeitfenster keine NFL-Spiele an oder die Buchmacher-Linien sind noch nicht geöffnet.")
    else:
        report = analyze_nfl(matches)
        send_telegram_message(report)
