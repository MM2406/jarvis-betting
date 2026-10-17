import os
import requests
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

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
    now = datetime.now(timezone.utc)
    
    # Am Wochenende (Fr=4, Sa=5, So=6): 12 Stunden Fokus
    # Unter der Woche (Mo-Do): 20 Stunden für den gesamten Spieltag
    if now.weekday() in [4, 5, 6]:
        time_window = timedelta(hours=12)
    else:
        time_window = timedelta(hours=20)
        
    cutoff_time = now + time_window

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
            commence = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            if now <= commence <= cutoff_time:
                bookies = match.get("bookmakers", [])
                if not bookies:
                    continue
                
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
                
                time_str = commence.strftime("%d.%m. %H:%M UTC")
                match_line = f"[{match['sport_title']}] {match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(market_details)}"
                matches_summary.append(match_line)
                
    return "\n".join(matches_summary[:200])

def analyze_with_jarvis(matches_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Du bist 'JARVIS', ein hochpräziser Sportwetten-Analyst und Cyber-Butler.
    Hier sind die anstehenden Partien des aktuellen Zeitfensters inklusive Buchmacher-Quoten (H2H und Over/Under Totals):
    
    {matches_text}
    
    DEINE STRATEGIE & WETTLOGIK:
    1. **Fakten-Check:** Nutze zwingend die Google-Suche, um tagesaktuelle News, Ausfälle, Formkurven und Matchups zu prüfen.
    2. **Sportarten-Regeln:**
       - **NBA, NHL, NFL:** Nutze primär die Over/Under-Linien (Totals)! Reine Siegwetten nur bei überwältigender Faktenlage.
       - **Spielerwetten (Player Props):** Recherchiere für Top-Partien in NFL, NBA oder NHL gezielt starke Props (z. B. NFL TD-Scorer, Rushing/Receiving Yards, NHL Scorer-Punkte, NBA Punkte Over/Under).
       - **Fußball:** Favoriten-Siegwetten, Doppelte Chance oder Tor-Totals (Over/Under).
    3. **Kombi-Architektur:** 
       - Erstelle mindestens zwei größere Kombis (eine 3er-Kombi und eine 4er-Kombi).
       - Achte auf solide Einzelquoten (ca. 1.30 bis 1.70).
       - Durchmische die Sportarten.
    
    FORMATIERUNG & HTML-DESIGN (SEHR WICHTIG):
    Verwende KEIN Markdown (keine ###, keine **, keine `). Verwende ausschließlich saubere HTML-Tags für Telegram:
    - Fett: <b>Text</b>
    - Kursiv: <i>Text</i>
    - Keine anderen HTML-Tags!
    
    STRUKTUR:
    Starte exakt mit:
    <b>Guten Tag, Sir. Hier ist Ihr optimiertes Sportwetten-Dossier:</b>

    Gliedere die Sektionen optisch sauber:
    
    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>1. DAS CROSS-SPORT DOUBLE (2er-Kombi)</b>
    <i>Fokus auf maximale statistische Stabilität</i>
    
    • <b>[Liga] Team A vs. Team B</b>
      Tipp: <b>[Wettauswahl]</b> | Quote: <b>[Quote]</b>
      <i>Fakten:</i> [1-2 präzise Sätze]
    
    <b>Gesamtquote: [Quote]</b>

    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>2. DIE CROSS-SPORT 3er-KOMBI</b>
    ...
    
    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>3. DIE HIGH-VALUE 4er-KOMBI</b>
    ...

    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>4. DAS TOTALS-SPEZIAL (3er-Kombi nur Over/Under)</b>
    ...

    <b>━━━━━━━━━━━━━━━━━━━━</b>
    <b>5. PLAYER-PROPS SPECIAL (Solo-Empfehlungen)</b>
    • <b>[Liga] Spielername (Team) – [Wettart]</b>
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
    
    # Intelligenter Text-Splitter: Trennt nur an Absätzen, nie mitten im Wort
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
        
        # Fallback auf reinen Text, falls Gemini aus Versehen ein falsches HTML-Tag generiert hat
        if response.status_code != 200:
            print("HTML parsing fehlgeschlagen, sende als reinen Text...")
            payload.pop("parse_mode", None)
            res_fallback = requests.post(url, json=payload)
            if res_fallback.status_code != 200:
                raise Exception(f"Fehler beim Telegram-Versand: {res_fallback.text}")

if __name__ == "__main__":
    matches = fetch_matches()
    if not matches:
        matches = "Keine passenden Spiele im Zeitfenster gefunden."
    analysis = analyze_with_jarvis(matches)
    send_telegram_message(analysis)
