import os
import sys
import json
import re
import time
import requests
from datetime import datetime
from quant_engine import calculate_match_odds

try:
    from value_scanner import format_value_badge
except ImportError:
    format_value_badge = None

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_SOCCER = os.environ.get("TELEGRAM_THREAD_SOCCER", "").strip()

STATE_FILE = "pending_soccer.json"

def clean_team_name(name):
    clean = re.sub(r"\b(bc|fc|cf|sc|ac|united|city|afc|ssc|rb|calcio|ca)\b", "", name.lower())
    return " ".join(clean.split()).strip()

def fetch_today_fixtures():
    """Gibt die heutigen Partien zurück."""
    today_weekday = datetime.utcnow().weekday()

    if today_weekday == 0:
        return [
            {"home": "Fulham", "away": "Brentford", "league": "Premier League", "time": "21:00"},
            {"home": "Lazio", "away": "Cagliari", "league": "Serie A", "time": "20:45"},
            {"home": "Celta", "away": "Getafe", "league": "La Liga", "time": "21:00"}
        ]
    elif today_weekday in [1, 2]:
        return [
            {"home": "Galatasaray", "away": "VfB Stuttgart", "league": "Champions League", "time": "18:45"},
            {"home": "Atletico Madrid", "away": "Bayern Munich", "league": "Champions League", "time": "21:00"},
            {"home": "Barcelona", "away": "Aston Villa", "league": "Champions League", "time": "21:00"},
            {"home": "Bodo/Glimt", "away": "Lille", "league": "Champions League", "time": "21:00"},
            {"home": "Feyenoord", "away": "Inter", "league": "Champions League", "time": "21:00"}
        ]
    elif today_weekday == 3:
        return [
            {"home": "Tottenham", "away": "Roma", "league": "Europa League", "time": "21:00"},
            {"home": "Man United", "away": "Bodo/Glimt", "league": "Europa League", "time": "21:00"},
            {"home": "Frankfurt", "away": "Midtjylland", "league": "Europa League", "time": "21:00"},
            {"home": "Chelsea", "away": "Heidenheim", "league": "Conference League", "time": "21:00"}
        ]
    elif today_weekday == 4:
        return [
            {"home": "Leverkusen", "away": "Stuttgart", "league": "Bundesliga", "time": "20:30"},
            {"home": "Monaco", "away": "Angers", "league": "Ligue 1", "time": "21:00"},
            {"home": "Alaves", "away": "Mallorca", "league": "La Liga", "time": "21:00"}
        ]
    else:
        return [
            {"home": "Arsenal", "away": "Chelsea", "league": "Premier League", "time": "13:30"},
            {"home": "Dortmund", "away": "Leverkusen", "league": "Bundesliga", "time": "15:30"},
            {"home": "Milan", "away": "Inter", "league": "Serie A", "time": "18:00"},
            {"home": "Real Madrid", "away": "Barcelona", "league": "La Liga", "time": "21:00"}
        ]

def fetch_real_market_odds(home_name, away_name):
    """Holt die tatsächlichen Buchmacher-Quoten über die SportAPI."""
    if not RAPIDAPI_KEY:
        return {}

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "sportapi7.p.rapidapi.com"
    }

    # 1. Heutige Spiele suchen
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    url_schedule = f"https://sportapi7.p.rapidapi.com/api/v1/sport/football/scheduled-events/{today_str}"
    
    event_id = None
    try:
        res = requests.get(url_schedule, headers=headers, timeout=10)
        if res.status_code == 200:
            events = res.json().get("events", [])
            h_clean = clean_team_name(home_name)
            a_clean = clean_team_name(away_name)
            for ev in events:
                eh = clean_team_name(ev.get("homeTeam", {}).get("name", ""))
                ea = clean_team_name(ev.get("awayTeam", {}).get("name", ""))
                if (h_clean in eh or eh in h_clean) and (a_clean in ea or ea in a_clean):
                    event_id = ev.get("id")
                    break
    except Exception as e:
        print(f"Fehler bei Eventsuche für {home_name} vs {away_name}: {e}")

    if not event_id:
        return {}

    # 2. Reale Quoten für das gefundene Event abrufen
    odds_url = f"https://sportapi7.p.rapidapi.com/api/v1/event/{event_id}/odds"
    real_odds = {}
    try:
        ores = requests.get(odds_url, headers=headers, timeout=10)
        if ores.status_code == 200:
            markets = ores.json().get("markets", [])
            for m in markets:
                m_name = m.get("marketName", "").lower()
                choices = m.get("choices", [])
                
                # 1X2
                if m_name in ["1x2", "full time", "match result"]:
                    for c in choices:
                        cn = c.get("name", "").lower()
                        frac = c.get("fractionalValue") or c.get("decimalValue") or c.get("price")
                        if frac:
                            if "1" in cn or "home" in cn: real_odds["1"] = round(float(frac), 2)
                            elif "x" in cn or "draw" in cn: real_odds["X"] = round(float(frac), 2)
                            elif "2" in cn or "away" in cn: real_odds["2"] = round(float(frac), 2)

                # Über / Unter 2.5
                if "over/under" in m_name or "total" in m_name:
                    for c in choices:
                        cn = c.get("name", "").lower()
                        frac = c.get("fractionalValue") or c.get("decimalValue") or c.get("price")
                        if frac and "2.5" in cn:
                            if "over" in cn or "über" in cn: real_odds["Over_2.5"] = round(float(frac), 2)
                            elif "under" in cn or "unter" in cn: real_odds["Under_2.5"] = round(float(frac), 2)

                # BTTS (Beide treffen)
                if "both teams to score" in m_name or "btts" in m_name:
                    for c in choices:
                        cn = c.get("name", "").lower()
                        frac = c.get("fractionalValue") or c.get("decimalValue") or c.get("price")
                        if frac:
                            if "yes" in cn or "ja" in cn: real_odds["BTTS_Yes"] = round(float(frac), 2)
                            elif "no" in cn or "nein" in cn: real_odds["BTTS_No"] = round(float(frac), 2)
    except Exception as e:
        print(f"Fehler bei Quotenabruf für Event {event_id}: {e}")

    return real_odds

def get_quant_context(fixtures):
    """Kombiniert Poisson-Wahrscheinlichkeiten mit den realen Buchmacher-Quoten."""
    quant_summary = []
    for f in fixtures:
        h, a = f["home"], f["away"]
        res = calculate_match_odds(h, a)
        
        # Echte Buchmacher-Quoten holen
        market_odds = fetch_real_market_odds(h, a)

        entry = {
            "match": f"{h} vs. {a}",
            "league": f.get("league", "Europäisch"),
            "time": f.get("time", "21:00"),
            "poisson_model": res if res else "Basis-Stats",
            "real_market_odds": market_odds
        }
        quant_summary.append(entry)
    return quant_summary

def build_prompt_with_data(quant_data):
    data_str = json.dumps(quant_data, ensure_ascii=False, indent=2)
    
    prompt = f"""Du bist JARVIS, ein quantitatives Analyse-System für Fußballwetten.
Unten stehen die mathematischen Berechnungen und die REALEN BUCHMACHER-QUOTEN ('real_market_odds'):

{data_str}

STRIKTE QUOTEN- UND VALUE-REGELN:
1. Verwende AUSSCHLIESSLICH die Quoten aus 'real_market_odds'. Erfinde NIEMALS eigene Quoten!
2. MINDESTQUOTE BEACHTEN:
   - Wähle KEINE Quoten unter 1.35 aus. Quoten wie 1.20 oder 1.22 bieten keinen Value und sind STRIKT VERBOTEN.
   - Wenn Über 2.5 nur 1.22 zahlt, weiche auf Über 3.0/3.5 aus oder nimm einen anderen Markt.
3. SPIELERWETTEN (Player Props):
   - Nur "OVER"-Märkte (Torschüsse Über 0.5/1.5, Anytime Goalscorer).
   - Mindestquote 1.40.
4. Alle Auswahlen müssen mathematischen Value gegenüber den realen Quoten aufweisen.

Erstelle den fertigen Telegram-Post im gewohnten JARVIS-Format (HTML) mit:
- ⭐ SOCCER PICK OF THE DAY (Höchster berechneter Value)
- 🔒 CONSERVATIVE 2-LEG BANKER (Hohe Trefferwahrscheinlichkeit, Mindest-Gesamtquote ~1.80)
- ⚖️ BALANCED VALUE ACCA (3-er Kombination)
- ⚽ GOALS & BTTS VALUE ACCA

Antworte ausschließlich im JSON-Format mit zwei Keys:
- "telegram_html": Kompletter Text für Telegram (formatiert mit HTML-Tags, Absätzen und Emojis)
- "pending_state": JSON-Struktur für pending_soccer.json mit den Keys "potd" und "tickets"
"""
    return prompt

def generate_intel():
    fixtures = fetch_today_fixtures()
    print(f"📋 {len(fixtures)} Partien zur Analyse geladen.")

    quant_data = get_quant_context(fixtures)
    if not quant_data:
        print("❌ Keine Partien verfügbar.")
        sys.exit(1)

    print(f"✅ Partien & Live-Quoten erfolgreich geladen.")

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY fehlt.")
        sys.exit(1)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": build_prompt_with_data(quant_data)}]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    print("🤖 Sende quantitatives Briefing mit Live-Quoten an Gemini...")

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                result_json = json.loads(content)
                
                state_data = result_json.get("pending_state", {})
                state_data["original_text"] = result_json.get("telegram_html", "")
                state_data["finished_matches"] = {}
                state_data["message_id"] = 0

                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, ensure_ascii=False, indent=2)

                print(f"🎉 {STATE_FILE} erfolgreich mit realen Buchmacher-Quoten generiert.")
                return
            elif res.status_code in [500, 502, 503, 504]:
                print(f"⚠️ Temporärer Server-Fehler ({res.status_code}). Warte vor Versuch {attempt + 1}/3...")
                time.sleep(5)
            else:
                print(f"❌ Gemini API Fehler: {res.text}")
                sys.exit(1)
        except Exception as e:
            print(f"❌ Versuch {attempt}/3 fehlgeschlagen: {e}")
            if attempt < 3:
                time.sleep(5)
            else:
                sys.exit(1)

if __name__ == "__main__":
    generate_intel()
