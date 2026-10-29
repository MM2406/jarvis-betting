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
TELEGRAM_THREAD_ID = os.environ.get("TELEGRAM_MONEYRACE_THREAD_ID", "").strip()

LOCAL_TZ = ZoneInfo("Europe/Berlin")
STATE_FILE = "moneyrace_state.json"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except ValueError:
            pass
    try:
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            payload.pop("parse_mode", None)
            requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "active": True,
            "level": 1,
            "bankroll": 5.0,
            "target": 100.0,
            "pending_pick": None,
            "history": []
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def generate_progress_bar(current, target=100.0, length=7):
    pct = min(1.0, max(0.0, current / target))
    filled = min(length, max(1, int(pct * length)))
    bar = "🟩" * filled + "⬜" * (length - filled)
    return bar, f"{pct * 100:.1f}%"

def fetch_real_odds():
    sports = [
        "basketball_nba",
        "icehockey_nhl",
        "soccer_germany_bundesliga",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_usa_mls"
    ]
    candidate_odds = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=28)

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for match in data:
                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        bookies = match.get("bookmakers", [])
                        if not bookies:
                            continue
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M Uhr")
                        
                        # Suche gezielt nach realen Quoten zwischen 1.50 und 1.75
                        for m in bookies[0].get("markets", []):
                            m_key = m.get("key")
                            for outcome in m.get("outcomes", []):
                                price = outcome.get("price", 0.0)
                                if 1.50 <= price <= 1.75:
                                    market_desc = f"{outcome['name']}"
                                    if m_key == "totals":
                                        market_desc = f"{outcome['name']} {outcome.get('point', '')} Goals/Points"
                                    candidate_odds.append(
                                        f"Sport: {sport} | Match: {match['home_team']} vs. {match['away_team']} ({time_str}) | Markt/Tipp: {market_desc} | Reale Quote: {price}"
                                    )
        except Exception as e:
            print(f"Fehler bei {sport}: {e}")

    print(f"Geprüfte Quoten im Korridor gesammelt: {len(candidate_odds)}")
    return "\n".join(candidate_odds[:45])

def run_moneyrace():
    state = load_state()
    
    if not state.get("active", True):
        print("Moneyrace pausiert oder beendet.")
        return

    # 1. AUSWERTUNG eines noch offenen Picks
    if state.get("pending_pick"):
        pick = state["pending_pick"]
        prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgende Wette:
Event: {pick.get('event')}
Sportart: {pick.get('sport')}
Tipp: {pick.get('selection')} (Quote: {pick.get('odds')})
Datum: {pick.get('date')}

REGELN:
1. Prüfe, ob die Partie bereits offiziell beendet ist. Falls noch nicht begonnen oder laufend, gib 'PENDING' aus.
2. Markiere mit 'WON', wenn der Tipp aufgegangen ist, oder 'LOST', wenn er verloren ging.
3. Bei Spielabsage oder Push gib 'VOID' aus.

Antworte strikt in diesem Format:
RESULT: WON oder LOST oder PENDING oder VOID
INFO: Kurze Begründung mit dem exakten Endergebnis.
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt_settle}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }
        
        reply = ""
        for attempt in range(1, 4):
            try:
                res = requests.post(url, json=payload, timeout=60)
                if res.status_code == 200:
                    reply = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    break
                elif res.status_code in [500, 502, 503, 504]:
                    time.sleep(6)
            except Exception as e:
                print(f"Versuch {attempt}/3 Fehlgeschlagen: {e}")
                time.sleep(6)

        if "RESULT: WON" in reply:
            return_amt = round(state["bankroll"] * float(pick["odds"]), 2)
            profit = round(return_amt - state["bankroll"], 2)
            state["history"].append({
                "level": state["level"],
                "pick": pick,
                "result": "WON",
                "return": return_amt
            })
            state["bankroll"] = return_amt
            state["level"] += 1
            state["pending_pick"] = None

            bar, pct_str = generate_progress_bar(state["bankroll"], state["target"])

            if state["bankroll"] >= state["target"]:
                msg = f"""🏆 <b>MONEYRACE ERFOLGREICH BEENDET!</b> 🎯

Endstand: <b>{state['bankroll']:.2f} €</b> (Start: 5.00 €)
Ziel von 100.00 € geknackt!
Alle Stufen fehlerfrei gemeistert."""
                send_telegram(msg)
                state["active"] = False
                save_state(state)
                return
            else:
                next_approx = round(state["bankroll"] * 1.55, 2)
                msg = f"""✅ <b>MONEYRACE STUFE {state['level'] - 1} GEWONNEN!</b>

📌 <b>Tipp:</b> {pick['selection']} @ {pick['odds']} ➔ <b>TREFFER!</b>
💰 <b>Rücklauf:</b> +{profit:.2f} €
🏦 <b>Neuer Kontostand:</b> <b>{state['bankroll']:.2f} €</b>

Progress: [{bar}] <b>{pct_str}</b> zum Ziel
➔ Weiter mit <b>Stufe {state['level']}</b> (Ziel nächste Stufe: ~{next_approx:.2f} €)!"""
                send_telegram(msg)
                save_state(state)

        elif "RESULT: LOST" in reply:
            state["history"].append({
                "level": state["level"],
                "pick": pick,
                "result": "LOST"
            })
            msg = f"""❌ <b>MONEYRACE CRASH IN STUFE {state['level']}</b>

📌 <b>Verlorener Pick:</b> {pick['selection']} ({pick['event']})
Verlust: -{state['bankroll']:.2f} €
🔄 <b>Neustart:</b> Reset auf Stufe 1 mit 5.00 €."""
            send_telegram(msg)
            state["level"] = 1
            state["bankroll"] = 5.0
            state["pending_pick"] = None
            save_state(state)

        elif "RESULT: VOID" in reply:
            msg = f"""🟡 <b>MONEYRACE PICK VOID / ABGESAGT</b>
Spiel: {pick['event']} wurde storniert oder verschoben. Einsatz bleibt bei {state['bankroll']:.2f} €."""
            send_telegram(msg)
            state["pending_pick"] = None
            save_state(state)
        else:
            print("Spiel noch offen oder läuft. Keine Aktion.")
            return

    # 2. NEUEN PICK AUS ECHTEN QUOTEN AUSWÄHLEN
    available_odds_text = fetch_real_odds()
    if not available_odds_text:
        print("Keine passenden Quoten im 1.50-1.75 Korridor gefunden.")
        return

    prompt_pick = f"""
Du bist 'JARVIS MONEYRACE QUANT'.
Wir spielen ein Moneyrace von 5.00 € auf 100.00 €.
Aktueller Status:
- Stufe: {state['level']} (von ca. 7 Stufen)
- Einsatz: {state['bankroll']:.2f} € (All-In)
- Ziel: {state['target']:.2f} €

Hier sind reale, geprüfte Buchmacherquoten, die exakt im geforderten Korridor (1.50 bis 1.75) liegen:
{available_odds_text}

Wähle aus DIESER Liste den mathematisch stärksten Pick (+EV).
WICHTIG: Übernimm die Quote EXAKT wie in der Liste angegeben (keine Quoten schätzen oder verändern!).

FORMATIERE AM ENDE EXAKT EIN JSON-OBJEKT:
---JSON---
{{
  "sport": "Sportart",
  "event": "Team A vs Team B",
  "start_time": "TT.MM. HH:MM Uhr",
  "date": "{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')}",
  "selection": "Exakter Markt & Tipp",
  "odds": 1.58,
  "model_prob": "67.4%",
  "fair_odds": "1.48",
  "edge": "+4.1%",
  "reason": "Prägnante Begründung der taktischen und statistischen Kante"
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt_pick}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for attempt in range(1, 4):
        try:
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                if "---JSON---" in raw_text:
                    json_str = raw_text.split("---JSON---")[1].strip()
                    new_pick = json.loads(json_str)
                    state["pending_pick"] = new_pick
                    save_state(state)

                    pot_return = round(state["bankroll"] * float(new_pick["odds"]), 2)
                    profit = round(pot_return - state["bankroll"], 2)
                    next_step_target = round(pot_return * 1.55, 2)
                    bar, pct_str = generate_progress_bar(state["bankroll"], state["target"])

                    msg = f"""🎯 <b>JARVIS MONEYRACE • STUFE {state['level']} / 7</b>
Progress: [{bar}] <b>{pct_str}</b> zum Ziel

Einsatz:  <b>{state['bankroll']:.2f} €</b> (All-In)
Ziel:     <b>{state['target']:.2f} €</b> (Rest: {state['target'] - state['bankroll']:.2f} €)

━━━━━━━━━━━━━━━━━━━━
📌 <b>Match:</b>   {new_pick.get('event')}
🏆 <b>Sport:</b>   {new_pick.get('sport')}
⏰ <b>Beginn:</b>  {new_pick.get('start_time', 'Heute')}
🎯 <b>Tipp:</b>    <b>{new_pick.get('selection')}</b>
📈 <b>Quote:</b>   {new_pick.get('odds')} (Geprüfte Buchmacherquote)
💰 <b>Return:</b>  <b>{pot_return:.2f} €</b> (+{profit:.2f} €)

━━━━━━━━━━━━━━━━━━━━
🔍 <b>EDGE & QUANT-ANALYSE</b>
• Modell-Chance: {new_pick.get('model_prob', 'N/A')} | Fair Odds: ~{new_pick.get('fair_odds', 'N/A')}
• Mathematischer Edge: <b>{new_pick.get('edge', '+EV')}</b>
• Rationale: <i>{new_pick.get('reason')}</i>

━━━━━━━━━━━━━━━━━━━━
🗺️ <b>NÄCHSTER SCHRITT</b>
Bei Win geht es mit <b>{pot_return:.2f} €</b> direkt in Stufe {state['level'] + 1} (Ziel: ~{next_step_target:.2f} €)."""

                    send_telegram(msg)
                    print("Neuer Moneyrace-Pick erfolgreich gesetzt.")
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
    run_moneyrace()
