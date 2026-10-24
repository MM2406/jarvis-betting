import os
import json
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
    ("soccer_germany_bundesliga", "1. Bundesliga GER"),
    ("soccer_germany_bundesliga2", "2. Bundesliga GER"),
    ("soccer_austria_bundesliga", "Admiral Bundesliga AUT"),
    ("soccer_epl", "Premier League"),
    ("soccer_efl_champ", "Championship ENG"),
    ("soccer_spain_la_liga", "La Liga"),
    ("soccer_italy_serie_a", "Serie A"),
    ("soccer_france_ligue_one", "Ligue 1"),
    ("soccer_uefa_champs_league", "Champions League"),
    ("soccer_uefa_europa_league", "Europa League"),
    ("soccer_uefa_conference_league", "Conference League")
]

def fetch_soccer_matches():
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=30)

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

    prompt = f"""
Du bist 'JARVIS SOCCER QUANT PRO', ein quantitativer Analyst für Profifußball mit Fokus auf Value Betting (+EV) und Buchmacher-In-Effizienzen.
Hier sind die realen Partien inklusive Buchmacher-Quoten und Spielzeiten:
{matches_text}

STRIKTE QUANTITATIVE REGELN:
1. MATHEMATISCHER EDGE (+EV):
   - Schätze für jeden Kandidaten die reale Wahrscheinlichkeit P(Win).
   - Ein Tipp darf NUR gewählt werden, wenn P(Win) > (1 / Quote). Beispiel: Bei Quote 2.00 muss deine geschätzte Eintrittschance mindestens 54% betragen.
2. PICK OF THE DAY (SINGLE BET):
   - Wähle die eine Einzelwette des Tages mit dem absolut höchsten positiven Erwartungswert (+EV) im Quotenbereich 1.70 - 2.20.
3. INJURY- & LINEUP-FILTER:
   - Nutze die Google-Suche aktiv für Ausfälle.
   - Wähle für Torschützen-Tipps NIEMALS Spieler mit Verletzungs-Status, 'Questionable' oder hoher Rotationsgefahr. Nur bestätigte Starter / Stammkräfte.
4. KORRELATIONS- & WIDERSPRUCHS-CHECK:
   - Keine widersprüchlichen Picks über verschiedene Scheine hinweg (z. B. nicht auf einem Schein 'Team A gewinnt' und auf einem anderen 'Unter 1.5 Tore' gegen Team A).
5. SYSTEMWETTEN-EMPFEHLUNG:
   - Gib bei jedem 3er-Ticket explizit an, ob es als reine 3er-Kombi oder als '2 aus 3'-System gespielt werden sollte.
6. GENAUE ANSTOSSZEITEN: Jeder Pick MUSS die lokale Uhrzeit (MESZ/MEZ) enthalten.

FORMAT-VORGABE (Telegram-HTML: <b>fett</b>, <i>kursiv</i> - kein Markdown):
<b>⚽ JARVIS FOOTBALL INTEL & VALUE REPORT</b>
<i>Quantitatives Dossier mit +EV-Filter & Spieltags-Analysen</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>⭐ PICK OF THE DAY (Einzelwette - Höchster +EV)</b>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Geschätzte Chance:</i> [X]%
<i>Edge:</i> [Prägnante Begründung: xG-Vorteil, Ausfälle beim Gegner oder System-Vorteil]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>1. DIE BANKER-DOPPELCHANCE (2er-Double)</b>
<i>Stabile Kanten (Quote ca. 2.10 - 2.60)</i>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b>
<i>Edge:</i> [Taktische Stabilität]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>2. GOALS & BTTS VALUE TICKET (3er-Kombi)</b>
<i>Fokus auf ineffiziente Tor-Märkte (Quote ca. 4.00 - 6.50)</i>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b> | <i>Strategie:</i> <b>[Reine Kombi ODER 2 aus 3 System]</b>
<i>Edge:</i> [Offensiv-/Defensiv-Metriken beider Paarungen]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>3. MULTI-LEAGUE VALUE TICKET (3er-Kombi)</b>
<i>Ausgewählte Ligen-Kombination (Quote ca. 4.50 - 7.50)</i>
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
- <b>[Uhrzeit] [Liga] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote)
<b>Gesamtquote: [Quote]</b> | <i>Strategie:</i> <b>[Reine Kombi ODER 2 aus 3 System]</b>
<i>Edge:</i> [Matchup-Diskrepanz]

<b>━━━━━━━━━━━━━━━━━━━━</b>
<b>4. VALUE TORSCHÜTZE / SPECIAL PICK</b>
- <b>[Uhrzeit] Spieler (Team, Liga) vs. Gegner: [Torschütze / Scorer]</b> | Quote: <b>[Quote]</b>
<i>Lineup-Status:</i> Stammspieler (Fit) | Elfmeterschütze: [Ja/Nein]
<i>Spotlight:</i> [Form und gegnerische Defensiv-Lücken]

---JSON_DATA---
```json
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Heim vs Auswärts", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.30, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.50}}, {{"match": "M2", "pick": "Pick", "odds": 1.53}}]}},
  "goals_ticket": {{"odds": 5.20, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.70}}, {{"match": "M2", "pick": "Pick", "odds": 1.75}}, {{"match": "M3", "pick": "Pick", "odds": 1.75}}]}},
  "multi_ticket": {{"odds": 5.50, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.75}}, {{"match": "M2", "pick": "Pick", "odds": 1.80}}, {{"match": "M3", "pick": "Pick", "odds": 1.75}}]}},
  "scorer": {{"player": "Name", "match": "Team vs Gegner", "odds": 2.40}}
}}
"""
config = types.GenerateContentConfig(
tools=[types.Tool(google_search=types.GoogleSearch())],
temperature=0.2
)
response = client.models.generate_content(
model="gemini-2.5-flash",
contents=prompt,
config=config
)
return response.text
def parse_and_save_bets(full_text):
if "---JSON_DATA---" in full_text:
parts = full_text.split("---JSON_DATA---")
report_text = parts[0].strip()
json_part = parts[1].replace("json", "").replace("", "").strip()
try:
bet_data = json.loads(json_part)
with open("pending_soccer.json", "w", encoding="utf-8") as f:
json.dump(bet_data, f, ensure_ascii=False, indent=2)
print("Picks erfolgreich in pending_soccer.json gespeichert.")
except Exception as e:
print(f"JSON Parsing-Fehler: {e}")
return report_text
return full_text
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
if name == "main":
matches = fetch_soccer_matches()
if not matches:
send_telegram_message("⚽ Jarvis Fußball Status: Keine Spiele in den hinterlegten Ligen im aktuellen Zeitfenster.")
else:
raw_output = analyze_soccer(matches)
clean_report = parse_and_save_bets(raw_output)
send_telegram_message(clean_report)
