import os
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Lokale Zeitzone für Mitteleuropa
LOCAL_TZ = ZoneInfo("Europe/Berlin")

def fetch_matches():
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return "Keine API-Verbindung zu The Odds API möglich."
    
    all_sports = res.json()
    target_keywords = [
        "soccer", "basketball", "americanfootball", "handball", 
        "tennis", "icehockey"
    ]
    
    selected_sports = []
    for s in all_sports:
        key = s["key"]
        if s.get("active") and any(k in key for k in target_keywords):
            selected_sports.append(key)

    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    
    # Am Wochenende: 12 Stunden Fokus | Unter der Woche: 20 Stunden
    if now_utc.weekday() in [4, 5, 6]:
        time_window = timedelta(hours=12)
    else:
        time_window = timedelta(hours=20)
        
    cutoff_time = now_utc + time_window

    for sport in selected_sports:
        url_odds = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        res_odds = requests.get(url_odds, params=params)
        if res_odds.status_code != 200:
            continue
            
        data = res_odds.json()
        for match in data:
            commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            if now_utc <= commence_utc <= cutoff_time:
                bookies = match.get("bookmakers", [])
                if not bookies:
                    continue
                
                # In lokale Uhrzeit (MEZ/MESZ) umrechnen
                commence_local = commence_utc.astimezone(LOCAL_TZ)
                time_str = commence_local.strftime("%d.%m. um %H:%M Uhr")
                
                market_details = []
                for market in bookies[0].get("markets", []):
                    m_key = market.get("key")
                    outcomes = market.get("outcomes", [])
                    if m_key == "h2h":
                        h2h_str = "H2H: " + ", ".join([f"{o['name']} ({o['price']})" for o in outcomes])
                        market_details.append(h2h_str)
                    elif m_key == "totals":
                        tot_str = "Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in outcomes])
                        market_details.append(tot_str)
                
                match_line = f"[{match['sport_title']}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(market_details)}"
                matches_summary.append(match_line)
                
    return "\n".join(matches_summary[:200])

def analyze_with_jarvis(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Du bist 'JARVIS', ein hochpräziser Sportwetten-Analyst und Cyber-Butler.
    Hier sind die anstehenden Partien des Zeitfensters mit lokaler deutscher/österreichischer Anstoßzeit und Quoten (H2H und Over/Under Totals):
    
    {matches_text}
    
    DEINE STRATEGIE & WETTLOGIK:
    1. **Fakten-Check:** Nutze zwingend die Google-Suche, um tagesaktuelle News, Ausfälle, Formkurven und Matchups zu prüfen.
    2. **Echte Durchmischung (Hybrid-Kombis - SEHR WICHTIG):**
       - Bündele NICHT alle Siegwetten in einer Kombi und alle Totals in einer anderen!
       - JEDE Kombiwette (egal ob 2er, 3er oder 4er) MUSS intern aus verschiedenen Sportarten und verschiedenen Märkten bestehen (z. B. 1x Fußball Doppelte Chance/Sieg + 1x NBA Totals Over/Under + 1x NHL Tore oder Player Prop).
       - Bei NBA, NHL und NFL nutzt du vorrangig Over/Under-Linien (Totals).
       - Bei Top-Spielen in NFL/NBA/NHL kannst du auch starke Player-Props per Google-Suche recherchieren.
    3. **Quoten-Disziplin:**
       - Einzelquoten in den Kombis sollten solide zwischen 1.30 und 1.70 liegen, um Umfaller zu minimieren.
    
    FORMATIERUNG & HTML-DESIGN:
    Verwende KEIN Markdown (keine ###, keine **, keine `). Verwende ausschließlich saubere HTML-Tags:
    - Fett: <b>Text</b>
    - Kursiv: <i>Text</i>
    - Gib bei JEDEM Spiel zwingend die Uhrzeit an!
    
    STRUKTUR:
    Starte exakt mit:
    <b>Guten Tag, Sir. Hier ist Ihr optimiertes Sportwetten-Dossier:</b>

    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>1. DAS HYBRID-DOUBLE (2er-Kombi)</b>
    <i>Fokus auf maximale statistische Stabilität (Zielquote 1.80 - 2.40)</i>
    • <b>[Liga] Team A vs. Team B ([Datum] um [Uhrzeit] Uhr)</b>
      Tipp: <b>[Wettauswahl]</b> | Quote: <b>[Quote]</b>
      <i>Fakten:</i> [1-2 präzise Sätze]
    <b>Gesamtquote: [Quote]</b>

    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>2. DIE CROSS-SPORT 3er-KOMBI</b>
    <i>Mischung aus Fußball + US-Sport Totals (Zielquote 2.80 - 4.50)</i>
    ...
    
    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>3. DIE HIGH-VALUE 4er-KOMBI</b>
    <i>4 Top-Picks quer durch Sportarten und Märkte (Zielquote 4.50 - 8.00)</i>
    ...

    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>4. PLAYER-PROPS & VALUE SPECIAL (Solo-Tipps)</b>
    • <b>[Liga] Spielername (Team) – [Wettart] ([Datum] um [Uhrzeit] Uhr)</b>
      Indikative Quote: <b>[Quote]</b>
      <i>Matchup-Analyse:</i> [1-2 Sätze Begründung]
    
    Schließe ab mit:
    <i>Protokoll abgeschlossen. Möge die mathematische Varianz heute zu Ihren Gunsten ausfallen, Sir.</i>
    """

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.25
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

    for idx, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        print(f"Teil {idx}/{len(chunks)} - Status Code: {response.status_code}")
        
        if response.
