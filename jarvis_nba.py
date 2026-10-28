import os
import sys
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")

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
        if TELEGRAM_THREAD_ID:
            try:
                payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
            except ValueError:
                pass

        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res2 = requests.post(url, json=payload, timeout=20)
            if res2.status_code != 200:
                print(f"Telegram Fehler: {res2.text}")

def fetch_nba_data():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    matches_summary = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=36)

    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
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
                            details.append("Moneyline: " + ", ".join([f"{o['name']} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "spreads":
                            details.append("Spread: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                        elif m_key == "totals":
                            details.append("Totals: " + ", ".join([f"{o['name']} {o.get('point', '')} ({o['price']})" for o in m.get("outcomes", [])]))
                    matches_summary.append(f"{match['home_team']} vs. {match['away_team']} ({time_str}) | {' // '.join(details)}")
    except Exception as e:
        print(f"Fehler bei NBA Odds API: {e}")

    print(f"NBA-Partien gesammelt: {len(matches_summary)}")
    return "\n".join(matches_summary)

def analyze_nba(matches_text):
    prompt = f"""
Du bist 'JARVIS NBA QUANT PRO', spezialisiert auf quantitative NBA-Analysen (Pace, Offensive/Defensive Rating, Matchup-Vorteile, Inactivity-Reports).
Recherchiere via Google Search nach aktuellen Ausfällen, Verletzungen und Matchup-News für die anstehende NBA-Slate.

Hier sind die realen NBA-Partien mit aktuellen Quoten:
{matches_text}

STRIKTE QUANTITATIVE LEITPLANKEN:
1. MATHEMATISCHER VALUE (+EV): P(Win) > (1 / Quote).
2. QUOTEN-KORRIDOR FÜR KOMBIS:
   - Sowohl DYNAMIC TOTALS als auch DYNAMIC PLAYER PROPS müssen eine Gesamtquote zwischen 2.75 und 4.50 anstreben.
   - Baue bevorzugt extrem solide 2er-Kombis (z.B. ~1.80 x ~1.85 = ~3.33) oder 3er-Kombis mit sichereren Linien/Puffern. Vermeide zwingend riskante 3er-Kombis mit Quoten über 5.00!
3. MINDESTQUOTE BANKER: Jeder Pick im Banker-Ticket muss mindestens Quote 1.35 aufweisen (keine unrentablen 1.15er-Picks). Gesamtquote 2.00 - 2.70.
4. PUFFER BEI TOTALS: Nur Totals wählen, bei denen dein Modell mindestens 4 bis 5 Punkte Differenz zur Buchmacher-Linie projiziert.

TICKET-STRUKTUR:
- ⭐ PICK OF THE DAY (Single Bet, Quote 1.75 - 2.20): Die stärkste Kante der Slate (Spread oder Moneyline).
- 1. NBA BANKER TICKET (Strikt 2er-Double, Gesamtquote 2.00 - 2.70): Picks mit extrem hoher Erfolgswahrscheinlichkeit (Min. 1.35 pro Pick).
- 2. DYNAMIC TOTALS VALUE COMBO (2 bis 4 Picks, Zielquote 2.75 - 4.50): Solide Over/Under-Picks mit klarem Pace-Edge.
- 3. DYNAMIC PLAYER PROPS MULTI-TICKET (2 bis 4 Picks, Zielquote 2.75 - 4.50): Punkte, Rebounds, Assists oder 3PM mit klarem Matchup-Vorteil.

FORMAT (Telegram-HTML: <b>fett</b>, <i>kursiv</i>):
<b>🏀 JARVIS NBA INTEL & VALUE REPORT</b>
<i>Quantitatives NBA-Dossier • Pace & Trench-Modelle • Valuedaten</i>

<b>━━━━━━━━━━━━━━━━━━━━</b>
⭐ <b>PICK OF THE DAY (Single Bet)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Fair Odds:</i> ~[Faire Quote] | <i>Modell-Kante:</i> +[X]%
<i>Matchup Edge:</i> [Ausführliche quantitative Begründung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
1. <b>NBA BANKER TICKET (2er-Double)</b>
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<b>Gesamtquote: [Produkt aller Quoten]</b>
<i>Modell-Edge:</i> [Begründung]

<b>━━━━━━━━━━━━━━━━━━━━</b>
2. <b>DYNAMIC TOTALS VALUE COMBO ([Anzahl]-Kombi)</b>
[Für jedes Spiel:]
- <b>[Uhrzeit] Heim vs. Auswärts</b> -> Pick: <b>[Pick]</b> (Quote: [Quote])
<i>Rationale:</i> [Pace/Defensiv-Begründung mit Puffer]
<b>Gesamtquote: [Produkt aller Quoten]</b>

<b>━━━━━━━━━━━━━━━━━━━━</b>
3. <b>DYNAMIC PLAYER PROPS MULTI-TICKET ([Anzahl]-Kombi)</b>
[Für jeden Spieler:]
- <b>[Spielername] ([Team])</b> -> Pick: <b>[Line & Pick]</b> (Quote: [Quote])
<i>Matchup Edge:</i> [Begründung via Usage, Matchup, Defense vs Position]
<b>Gesamtquote: [Produkt aller Quoten]</b>

---JSON_DATA---
{{
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "potd": {{"match": "Heim vs Auswärts", "pick": "Pick", "odds": 1.90}},
  "banker": {{"odds": 2.25, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.50}}, {{"match": "M2", "pick": "Pick", "odds": 1.50}}]}},
  "totals": {{"odds": 3.40, "picks": [{{"match": "M1", "pick": "Pick", "odds": 1.85}}, {{"match": "M2", "pick": "Pick", "odds": 1.84}}]}},
  "player_props": {{"odds": 3.30, "picks": [{{"player": "P1", "pick": "Pick", "odds": 1.80}}, {{"player": "P2", "pick": "Pick", "odds": 1.83}}]}}
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=120)
            if res.status_code == 200:
                return res.json()["candidates"][0]["content"]["parts"][0]["text"]
            elif res.status_code in [500, 502, 503, 504]:
                print(f"Versuch {attempt}/3: Gemini Server Status {res.status_code}. Warte 6 Sekunden...")
                time.sleep(6)
            else:
                res.raise_for_status()
        except Exception as e:
            print(f"Versuch {attempt}/3 fehlgeschlagen: {e}")
            if attempt < 3:
                time.sleep(6)
            else:
                return "ERROR"
    return "ERROR"

def parse_and_save_bets(full_text):
    if "---JSON_DATA---" in full_text:
        parts = full_text.split("---JSON_DATA---")
        report_text = parts[0].strip()
        try:
            bet_data = json.loads(parts[1].strip())
            with open("pending_nba.json", "w", encoding="utf-8") as f:
                json.dump(bet_data, f, ensure_ascii=False, indent=2)
            print("NBA Wetten in pending_nba.json gespeichert.")
        except Exception as e:
            print(f"JSON Parsing-Fehler: {e}")
        return report_text
    return full_text

if __name__ == "__main__":
    matches = fetch_nba_data()
    if not matches:
        send_telegram_message("🏀 <b>Jarvis NBA Status:</b> Keine Spiele im Zeitfenster.")
    else:
        raw_output = analyze_nba(matches)
        if raw_output != "ERROR":
            send_telegram_message(parse_and_save_bets(raw_output))
            print("✅ NBA Report erfolgreich gesendet.")
        else:
            send_telegram_message("⚠️ <b>Jarvis NBA Error:</b> KI-Generierung fehlgeschlagen.")
            sys.exit(1)
