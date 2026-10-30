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
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_SOCCER_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")
HISTORY_FILE = "soccer_history.json"

SOCCER_LEAGUES = [
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_austria_bundesliga",
    "soccer_usa_mls"
]

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except ValueError:
            pass

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"settled": [], "pending": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {HISTORY_FILE}: {e}")
        return {"settled": [], "pending": []}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {HISTORY_FILE}: {e}")

def settle_pending_picks(history):
    pending = history.get("pending", [])
    if not pending:
        print("Keine offenen Soccer-Picks zur Auswertung.")
        return history

    still_pending = []
    settled_now = []

    for item in pending:
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes Fußballspiel:
Match: {item.get('match')}
Wettbewerb: {item.get('league')}
Tipp: {item.get('pick')}
Datum: {item.get('date')}

REGELN:
1. Prüfe, ob das Match regulär beendet ist (nach 90 Min). Falls noch nicht begonnen oder live, antworte mit PENDING.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, sonst 'LOST'.
3. Bei Push (z.B. Handicap Unentschieden / Draw No Bet Push) gib 'VOID' aus.

Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Endergebnis (z.B. 2:1)
INFO: Kurze Begründung.
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                if "RESULT: WON" in text:
                    item["status"] = "WON"
                    settled_now.append(item)
                elif "RESULT: LOST" in text:
                    item["status"] = "LOST"
                    settled_now.append(item)
                elif "RESULT: VOID" in text:
                    item["status"] = "VOID"
                    settled_now.append(item)
                else:
                    still_pending.append(item)
            else:
                still_pending.append(item)
        except Exception as e:
            print(f"Fehler bei Abrechnung {item.get('match')}: {e}")
            still_pending.append(item)

    if settled_now:
        history["settled"].extend(settled_now)
        history["pending"] = still_pending
        save_history(history)

        won_count = sum(1 for p in settled_now if p["status"] == "WON")
        total_count = len(settled_now)

        msg = f"📊 <b>JARVIS SOCCER ABRECHNUNG</b>\nAusgewertete Tipps: <b>{won_count}/{total_count}</b> Treffer.\n"
        for p in settled_now:
            icon = "✅" if p["status"] == "WON" else ("❌" if p["status"] == "LOST" else "🟡")
            msg += f"\n{icon} <b>{p['match']}</b>\nTipp: {p['pick']} (@ {p.get('odds', 'N/A')})"
        send_telegram(msg)

    return history

def fetch_soccer_odds(already_tracked_matches):
    all_events = []
    now_utc = datetime.now(timezone.utc)
    now_hour = datetime.now(LOCAL_TZ).hour

    # Fenster je nach Schicht:
    # Vor 15 Uhr: Nachmittagsspiele (nächste 7 Std)
    # Nach 15 Uhr: Abendschlager (nächste 9 Std)
    window_hours = 7 if now_hour < 15 else 9
    cutoff = now_utc + timedelta(hours=window_hours)

    for sport in SOCCER_LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for match in data:
                    match_name = f"{match['home_team']} vs. {match['away_team']}"
                    # Bereits getrackte Partien nicht nochmals analysieren
                    if match_name in already_tracked_matches:
                        continue

                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue

                        odds_details = []
                        for m in bookies[0].get("markets", []):
                            m_key = m.get("key")
                            outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in m.get("outcomes", [])]
                            odds_details.append(f"{m_key}: {', '.join(outcomes)}")

                        all_events.append(
                            f"[{sport}] {match_name} ({time_str}) | Quoten: {' // '.join(odds_details)}"
                        )
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Gefundene Fußball-Partien für dieses Zeitfenster: {len(all_events)}")
    return "\n".join(all_events[:45])

def generate_soccer_report():
    history = load_history()
    settle_pending_picks(history)

    now_hour = datetime.now(LOCAL_TZ).hour
    # Morgens vor 10:00 Uhr: Nur Abrechnung
    if now_hour < 10:
        print("Morgen-Run: Abrechnung erledigt. Keine Picks vor 11:00 Uhr.")
        return

    tracked_matches = {p.get("match") for p in history.get("pending", [])}
    odds_data = fetch_soccer_odds(tracked_matches)

    if not odds_data:
        print(f"Keine passenden Fußballspiele für dieses Zeitfenster ({now_hour} Uhr) gefunden.")
        return

    edition = "MITTAGS-EDITION (Nachmittagsspiele)" if now_hour < 15 else "ABEND-EDITION (Flutlicht & Topspiele)"
    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS SOCCER QUANT' – ein autonomer, quantitativer Sportwetten-Hedgefonds-Algorithmus und Modellierer für europäischen Spitzenfußball.
Deine Aufgabe ist es, für den heutigen Spieltag ({today_str}) die {edition} zu berechnen und zu veröffentlichen.

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN (THE-ODDS-API FEED):
{odds_data}

================================================================================
ANALYSE- UND MODELLIERUNGS-FRAMEWORK (MATHEMATISCHE RICHTLINIEN):
================================================================================
1. DATENBASIS & VALIDIERUNG:
   - Nutze ausschließlich Partien, Quoten und Märkte aus dem obigen Live-Feed.
   - Falls ein Detail oder Spielerstatus unklar ist, validiere Aufstellungen, Ausfälle (Sperren, Verletzungen) und taktische Formationen via Google Search.
   - Kein Bauchgefühl: Jede Selektion muss auf quantitativen Metriken basieren (Non-Penalty xG, Expected Goals Against [xGA], Poisson-Verteilung der Torwahrscheinlichkeiten, Defensiv-Zulassungen und Transition-Pace).

2. ERWARTUNGSWERT (+EV) & QUOTEN-BEWERTUNG:
   - Berechne für jeden Pick die Modell-Wahrscheinlichkeit P(Win).
   - Fair Odds = 1 / P(Win).
   - Der mathematische Erwartungswert muss zwingend positiv sein: +EV% = (P(Win) * Quote - 1) * 100 > 0.
   - Weise den EV% für jede Selektion transparent im Text aus.

3. BUCHMACHER-KOMPATIBILITÄT & FALLBACK-LINIEN:
   - Da europäische Buchmacher (bet365, Tipico, DAZN Bet, Interwetten) nicht immer asiatische Teillinien (z. B. Asian Handicap -0.25 oder Over 2.75) führen, gibst du für JEDEN Tipp zwingend eine klassische Buchmacher-Alternative an.
   - Beispiele für Fallbacks:
     * Asian Handicap -0.25 -> Fallback: Draw No Bet (Sieg ohne Wette) oder 3-Weg Sieg
     * Over 2.75 Goals -> Fallback: Over 2.5 Goals
     * Asian Handicap -1.25 -> Fallback: Handicap (-1) oder Sieg
   - Weise für jede Selektion eine harte Quotenuntergrenze aus: 'Spielbar bis Mindestquote @ X.XX'. Fällt die Quote darunter, sinkt der EV auf 0 und die Wette darf nicht mehr gespielt werden.

4. DYNAMISCHES KOMBI-TICKET (KEIN KÜNSTLICHES LIMIT):
   - Begrenze dich im Kombi-Block NICHT künstlich auf 2 Spiele!
   - Scanne alle verfügbaren Partien: Wenn das Modell 3, 4 oder 5 Spiele mit statistisch sauberem Value (+EV) und stabiler Korrelation identifiziert, packe sie alle auf das Kombi-Ticket.
   - Mindestens 2 Spiele, maximal 5 Spiele. Wenn nur 2 Spiele echten Value haben, bleibt es bei 2.

5. BANKROLL-MANAGEMENT (UNIT-STAFFELUNG):
   - Pick of the Day (Single): 1.0 bis 2.0 Units (abhängig von Modell-Edge und Konvergenz)
   - Quant Value Acca (Kombi): 0.5 bis 1.0 Units
   - Goal-Market Spotlight: 0.5 bis 1.0 Units
   - Player Prop / Special: 0.5 bis 1.0 Units

================================================================================
AUSGABEFORMAT & TELEGRAM-HTML:
================================================================================
Gib ZUERST das saubere, unformatierte HTML für Telegram aus.
Verwende ausschließlich die erlaubten Telegram-Tags: <b>, <i>, <code>, <a>.
Schließe JEDES Tag sauber ab. Keine doppelten Leerzeilen.
Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
⚽ <b>JARVIS SOCCER INTEL • {edition}</b>
<i>Quantitative Match-Modelle • xG Edge • Value-Picks</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>SOCCER PICK OF THE DAY (Single Bet)</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
• <b>Wettbewerb:</b> [Name der Liga / Wettbewerb]
➔ <b>Haupt-Pick:</b> <b>[Präziser Markt &amp; Auswahl]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie / Fallback] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis Mindestquote @ [Quote]
💰 <b>Einsatz:</b> [1.0 - 2.0] Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge &amp; Modell-Rationale:</b>
[Ausführliche taktische und quantitative Herleitung: Gegenüberstellung von npxG vs. xGA der letzten 5 Spiele, Poisson-Torerwartung, defensive Schwachstellen des Gegners, Ausfälle und warum der Markt die Wahrscheinlichkeit falsch einpreist.]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA ([Anzahl]-er Kombi)</b>
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 3]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
[... ggf. Bein 4 und 5 ergänzen, falls Value vorhanden ...]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Kombi-Logik:</b> [Warum diese Partien statistisch robust sind und als Multi-Bet den höchsten Erwartungswert aufweisen.]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>GOAL-MARKET SPOTLIGHT (Totals / BTTS / Team-Totals)</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Over/Under / BTTS / Team-Total Auswahl]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Standard Über/Unter-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
📊 <b>Quant-Daten:</b> Poisson-Projizierte Tore: [X.XX] vs. [X.XX] | Modell-Chance: [XX.X]%
🔍 <b>Rationale:</b> [Analyse der Abschluss-Qualität, Chancen-Kreation beider Seiten, Pace und Umschaltmomente.]

━━━━━━━━━━━━━━━━━━━━
👟 <b>PLAYER PROP &amp; SPECIAL PICK</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Spielername: Torschütze / Schüsse aufs Tor (SoT) / Scorerpunkt]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Ausweich-Markt z. B. Team-Tor oder Spieler 1+ Schüsse] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [Individuelle Matchup-Vorteile, Schussvolumen pro 90 Minuten, Rollenverteilung bei Standards/Elfmetern und gegnerische Zulassungen in der defensiven Zone.]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "league": "soccer_germany_bundesliga",
    "pick": "Tipp des Pick of the Day",
    "odds": "1.85",
    "date": "{today_iso}"
  }}
]
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = full_reply
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        new_picks = json.loads(json_str)
                        for np in new_picks:
                            np["status"] = "PENDING"
                        history["pending"].extend(new_picks)
                        save_history(history)
                        print(f"{len(new_picks)} Soccer-Picks getrackt.")
                    except Exception as je:
                        print(f"Fehler beim Parsen der Tracking-Picks: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report)
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
    generate_soccer_report()
