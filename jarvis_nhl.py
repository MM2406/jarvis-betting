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

# Sicheres Routing ins NHL-Thema
TELEGRAM_THREAD_ID = (
    os.environ.get("TELEGRAM_THREAD_NHL", "").strip()
    or os.environ.get("TELEGRAM_THREAD_ID", "").strip()
)

LOCAL_TZ = ZoneInfo("Europe/Berlin")
PENDING_FILE = "pending_nhl.json"

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
            print(f"Ungueltige Thread-ID fuer NHL: {TELEGRAM_THREAD_ID}")

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

def settle_nhl_picks():
    pending = load_pending()
    open_picks = [p for p in pending if p.get("status") == "PENDING"]
    
    if not open_picks:
        print("Morgen-Settle: Keine offenen NHL-Picks zur Auswertung.")
        return

    print(f"Werte {len(open_picks)} offene NHL-Picks aus...")
    prompt = f"""
Du bist JARVIS NHL RESULT SETTLEMENT BOT.
Pruefe ueber Google Search die offiziellen Endergebnisse der folgenden NHL-Picks:

{json.dumps(open_picks, ensure_ascii=False, indent=2)}

REGELN:
1. Pruefe fuer jedes Spiel das offizielle Endergebnis (inkl. OT/SO).
2. Gib fuer jeden Pick den Status 'WON', 'LOST' oder 'VOID' zurueck.
3. Falls ein Spiel noch laeuft oder verschoben wurde, setze 'PENDING'.
4. Erstelle ein kompaktes Telegram-HTML-Recap mit Trefferquote und Units.
5. Gib am Ende exakt den Block '---JSON_SETTLED---' mit der aktualisierten JSON-Liste aus.

FORMAT:
🏒 <b>JARVIS NHL SETTLEMENT &amp; RECAP</b>
[Detaillierte Auswertung mit Endergebnissen und Unit-Bilanz]

---JSON_SETTLED---
[
  {{ ... original fields ..., "status": "WON|LOST|PENDING|VOID", "score": "3:2 OT" }}
]
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1}
    }
    
    try:
        res = requests.post(url, json=payload, timeout=75)
        if res.status_code == 200:
            ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if "---JSON_SETTLED---" in ans:
                parts = ans.split("---JSON_SETTLED---")
                report = parts[0].replace("```html", "").replace("```", "").strip()
                settled_json = parts[1].replace("```json", "").replace("```", "").strip()
                try:
                    updated = json.loads(settled_json)
                    save_pending(updated)
                except Exception as je:
                    print(f"Fehler beim Parsen der Abrechnung: {je}")
                send_telegram(report)
            else:
                send_telegram(ans)
    except Exception as e:
        print(f"Fehler bei NHL-Abrechnung: {e}")

def fetch_nhl_odds():
    url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            events = []
            now_utc = datetime.now(timezone.utc)
            cutoff = now_utc + timedelta(hours=18)
            for m in res.json():
                commence = datetime.fromisoformat(m["commence_time"].replace("Z", "+00:00"))
                if now_utc <= commence <= cutoff:
                    time_str = commence.astimezone(LOCAL_TZ).strftime("%H:%M Uhr")
                    bookies = m.get("bookmakers", [])
                    if not bookies:
                        continue
                    m_details = []
                    for mk in bookies[0].get("markets", []):
                        outcomes = [f"{o['name']} ({o.get('point', '')}): {o['price']}" for o in mk.get("outcomes", [])]
                        m_details.append(f"{mk.get('key')}: {', '.join(outcomes)}")
                    events.append(f"{m['home_team']} vs. {m['away_team']} ({time_str}) | {' // '.join(m_details)}")
            return "\n".join(events[:40])
    except Exception as e:
        print(f"Fehler bei NHL Odds: {e}")
    return ""

def run_nhl_intel():
    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 15:
        print(f"Es ist {now_hour}:00 Uhr MEZ. NHL-Picks werden erst ab 16:00 Uhr generiert.")
        return

    odds_data = fetch_nhl_odds()
    if not odds_data:
        print("Keine NHL-Spiele im Zeitfenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS NHL QUANT' – Spezialist für NHL-Eishockey und fortschrittliche Analytics (Corsi, Fenwick, xGF, Goalie GSAx).
Erstelle für heute ({today_str}) ein präzises Value-Dossier.

VERFÜGBARE PARTIEN & QUOTEN:
{odds_data}

RICHTLINIEN & MÄRKTE:
- Wähle ausschließlich Partien aus der obigen Liste.
- Berücksichtige bestätigte Starting Goalies, Back-to-Back-Faktoren und Special-Teams-Effizienz via Google Search.
- EISHOCKEY-REGEL: Weise IMMER aus, ob der Tipp 'inkl. OT/SO (Moneyline)' oder 'Reguläre Spielzeit (60 Min / 3-Weg)' ist.
- DYNAMISCHE ACCA: Kombiniere flexibel 2 bis 4 Spiele mit rechnerischem Vorteil (+EV). Kein starres 2-Spiele-Limit.
- BUCHMACHER-ALTERNATIVE: Gib immer eine Standard-Alternative an (z. B. ML inkl. OT statt Puckline -1.5).
- VALUE-GRENZE: Weise für jeden Tipp eine Mindestquote aus ('Spielbar bis @ X.XX').
- UNITS:
  * Pick of the Day: 1.0 bis 2.0 Units
  * Value Acca: 0.5 bis 1.0 Units
  * Totals/Goalie Spotlight: 0.5 bis 1.0 Units
  * Player Point / Goal Prop: 0.5 bis 1.0 Units

FORMATIERUNGS-REGELN FÜR TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzählung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

REPORT-HTML:
🏒 <b>JARVIS NHL INTEL DOSSIER</b>
<i>Advanced Hockey Analytics • Goalie Matchups • Value-Picks</i>

━━━━━━━━━━━━━━━━━━━━
⭐ <b>NHL PICK OF THE DAY (Single Bet)</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Haupt-Pick:</b> <b>[Moneyline inkl. OT / Puckline / 60 Min]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [1.0 - 2.0] Units
📊 <b>Quant-Daten:</b> Modell-Chance: [XX.X]% | Fair Odds: ~[X.XX] (<b>+[X.X]% EV</b>)
🔍 <b>Edge:</b> [Goalie GSAx Matchup, 5v5 High-Danger Chancen, Form, Special Teams]

━━━━━━━━━━━━━━━━━━━━
🔥 <b>QUANT VALUE ACCA ([Anzahl]-er Kombi)</b>
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 1]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 2]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
• [Uhrzeit] Uhr | [Heim] vs. [Gast] ➔ <b>[Tipp 3]</b> @ [Quote] (Alt: [Alternative] @ [Quote])
[... ggf. Bein 4 ergänzen falls Value vorhanden ...]
📈 <b>Gesamtquote:</b> <b>@[Quote]</b>
⚠️ <b>Value-Grenze:</b> Kombi spielbar bis @ [Quote]
💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Kombi-Logik:</b> [Warum diese Kombination mathematisch korreliert oder unabhängig starken Value bietet]

━━━━━━━━━━━━━━━━━━━━
🎯 <b>TOTALS &amp; GOALIE SPOTLIGHT</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Over/Under Wette]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative Over/Under Linie] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [Goalie Save %, Powerplay vs Penalty Kill Matchup, High-Danger xG]

━━━━━━━━━━━━━━━━━━━━
👟 <b>NHL PLAYER PROP SPOTLIGHT</b>
• <b>Match:</b> [Uhrzeit] Uhr | [Heimteam] vs. [Auswärtsteam]
➔ <b>Pick:</b> <b>[Spielername: Scorerpunkt (Punkte in der NHL) / Torschütze / Schüsse aufs Tor]</b> @ [Quote]
🔄 <b>Buchmacher-Alternative:</b> [Alternative Linie / Markt-Fallback] @ [Quote]
⚠️ <b>Value-Grenze:</b> Spielbar bis @ [Quote] | 💰 <b>Einsatz:</b> [0.5 - 1.0] Units
🔍 <b>Rationale:</b> [Eiszeit, PP1-Rolle, gegnerische Defensiv-Zulassungen auf dieser Position]

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NHL",
    "pick": "Team A Sieg (inkl. OT)",
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
                        pending = load_pending()
                        for np in new_picks:
                            np["status"] = "PENDING"
                        pending.extend(new_picks)
                        save_pending(pending)
                        print(f"{len(new_picks)} NHL-Picks getrackt.")
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
    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 11:
        settle_nhl_picks()
    else:
        run_nhl_intel()
