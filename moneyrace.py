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

MONEYRACE_SPORTS = [
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_austria_bundesliga",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_usa_mls",
    "basketball_nba",
    "basketball_euroleague",
    "icehockey_nhl",
    "icehockey_germany_del",
    "icehockey_sweden_shl"
]

def send_telegram(text, pin=False):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Credentials fehlen.")
        return None

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

    message_id = None
    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            message_id = res.json().get("result", {}).get("message_id")
        else:
            payload.pop("parse_mode", None)
            res_retry = requests.post(url, json=payload, timeout=25)
            if res_retry.status_code == 200:
                message_id = res_retry.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram-Fehler: {e}")

    if pin and message_id:
        try:
            pin_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/pinChatMessage"
            requests.post(pin_url, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "disable_notification": True}, timeout=15)
        except Exception as pe:
            print(f"Pin-Fehler: {pe}")

    return message_id

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "active": True,
            "step": 1,
            "bankroll": 5.00,
            "target": 100.00,
            "history": [],
            "current_bet": None
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {STATE_FILE}: {e}")
        return {"active": True, "step": 1, "bankroll": 5.00, "target": 100.00, "history": [], "current_bet": None}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {STATE_FILE}: {e}")

def render_progress_bar(step, total=7):
    filled = max(0, min(step, total))
    return "🟩" * filled + "⬜" * (total - filled)

def settle_current_bet(state):
    bet = state.get("current_bet")
    if not bet:
        print("Keine offene Moneyrace-Wette zur Abrechnung.")
        return state

    prompt_settle = f"""
Recherchiere via Google Search das offizielle Endergebnis für folgendes Spiel:
Match: {bet.get('match')}
Sportart: {bet.get('sport')}
Tipp: {bet.get('pick')}
Datum: {bet.get('date')}

WICHTIGE REGELN:
1. Prüfe, ob das Match bereits beendet ist. Falls noch nicht begonnen oder live, antworte zwingend mit PENDING.
2. Wenn der Tipp gewonnen hat, antworte mit 'RESULT: WON'.
3. Wenn der Tipp verloren hat, antworte mit 'RESULT: LOST'.
4. Bei Spielabsage oder Push (z.B. Draw No Bet Unentschieden) antworte mit 'RESULT: VOID'.

Format:
RESULT: WON oder LOST oder PENDING oder VOID
SCORE: Offizielles Endergebnis
INFO: Kurze Erklärung
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
            odds = float(bet.get("odds", 1.0))
            stake = float(state.get("bankroll", 5.0))

            if "RESULT: WON" in text:
                new_bankroll = round(stake * odds, 2)
                step = state.get("step", 1)
                state["bankroll"] = new_bankroll
                state["history"].append({**bet, "status": "WON", "return": new_bankroll})
                state["current_bet"] = None

                if new_bankroll >= state.get("target", 100.0):
                    msg = (
                        f"🏆 <b>MONEYRACE ERFOLGREICH BEENDET!</b>\n\n"
                        f"Ziel von {state.get('target', 100.0):.2f} € erreicht!\n"
                        f"Endstand nach Stufe {step}: <b>{new_bankroll:.2f} €</b>\n"
                        f"Herzlichen Glückwunsch an die Community!"
                    )
                    send_telegram(msg)
                    state["active"] = False
                else:
                    state["step"] = step + 1
                    bar = render_progress_bar(state["step"])
                    msg = (
                        f"✅ <b>MONEYRACE • STUFE {step} GEWONNEN!</b>\n\n"
                        f"Progress: [{bar}] (Stufe {state['step']}/7)\n"
                        f"📌 Match: <b>{bet.get('match')}</b>\n"
                        f"🎯 Tipp: {bet.get('pick')} (@ {odds:.2f})\n"
                        f"💰 Neuer Kontostand: <b>{new_bankroll:.2f} €</b>\n\n"
                        f"➔ Weiter geht es heute verlässlich um 18:00 Uhr mit <b>Stufe {state['step']}</b>!"
                    )
                    send_telegram(msg)

                save_state(state)

            elif "RESULT: LOST" in text:
                step = state.get("step", 1)
                state["history"].append({**bet, "status": "LOST", "return": 0.0})
                state["current_bet"] = None
                state["active"] = True
                state["step"] = 1
                state["bankroll"] = 5.00

                msg = (
                    f"❌ <b>MONEYRACE • STUFE {step} LEIDER VERLOREN</b>\n\n"
                    f"📌 Match: {bet.get('match')}\n"
                    f"🎯 Tipp: {bet.get('pick')} (@ {odds:.2f})\n\n"
                    f"Der Schein ging leider nicht auf. Das Moneyrace startet heute um 18:00 Uhr neu mit Stufe 1 (5.00 € Start-Bankroll)."
                )
                send_telegram(msg)
                save_state(state)

            elif "RESULT: VOID" in text:
                step = state.get("step", 1)
                state["current_bet"] = None
                msg = (
                    f"🟡 <b>MONEYRACE • STUFE {step} PUSH / UNENTSCHIEDEN</b>\n\n"
                    f"📌 Match: {bet.get('match')}\n"
                    f"Einsatz von {stake:.2f} € zurückerhalten. Die Stufe wird um 18:00 Uhr mit einem neuen Pick wiederholt."
                )
                send_telegram(msg)
                save_state(state)
            else:
                print("Partie noch nicht beendet (PENDING).")
    except Exception as e:
        print(f"Fehler bei Abrechnung: {e}")

    return state

def fetch_moneyrace_candidates():
    candidates = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=14)

    for sport in MONEYRACE_SPORTS:
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
                    commence_utc = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
                    if now_utc <= commence_utc <= cutoff:
                        time_str = commence_utc.astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M Uhr")
                        for bookie in match.get("bookmakers", []):
                            for market in bookie.get("markets", []):
                                m_key = market.get("key")
                                for outcome in market.get("outcomes", []):
                                    price = outcome.get("price", 0)
                                    if 1.50 <= price <= 1.75:
                                        point_str = f" ({outcome.get('point')})" if "point" in outcome else ""
                                        candidates.append({
                                            "sport": sport,
                                            "match": f"{match['home_team']} vs. {match['away_team']}",
                                            "time": time_str,
                                            "market": m_key,
                                            "name": outcome.get("name"),
                                            "detail": point_str,
                                            "price": price
                                        })
        except Exception as e:
            print(f"Fehler beim Laden von {sport}: {e}")

    print(f"Gefundene Kandidaten im 1.50-1.75 Korridor: {len(candidates)}")
    return candidates

def generate_moneyrace_pick():
    state = load_state()
    settle_current_bet(state)

    if not state.get("active", True):
        print("Moneyrace pausiert oder beendet.")
        return

    now_hour = datetime.now(LOCAL_TZ).hour
    if now_hour < 17:
        print(f"Morgen-Run ({now_hour} Uhr): Abrechnung abgeschlossen. Neuer Pick folgt verlässlich abends um 18:00 Uhr.")
        return

    if state.get("current_bet"):
        print("Aktuell läuft noch eine Wette für diese Stufe.")
        return

    candidates = fetch_moneyrace_candidates()
    if not candidates:
        print("Heute keine soliden Quoten im Zielkorridor 1.50 - 1.75 gefunden.")
        return

    formatted_candidates = "\n".join([
        f"[{c['sport']}] {c['match']} ({c['time']}) | Markt: {c['market']} -> {c['name']}{c['detail']} @ {c['price']}"
        for c in candidates[:45]
    ])

    step = state.get("step", 1)
    stake = state.get("bankroll", 5.0)
    target = state.get("target", 100.0)
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    progress_bar = render_progress_bar(step)

    prompt = f"""
Du bist 'JARVIS MONEYRACE QUANT' – ein risikobewusster Stufenwetten-Algorithmus.
Ziel: Aus {stake:.2f} € Schritt für Schritt {target:.2f} € machen.
Aktuelle Stufe: {step} / 7
Aktueller Einsatz (All-In): {stake:.2f} €
Balken: [{progress_bar}]

VERFÜGBARE PARTIEN IM ZIELKORRIDOR (1.50 - 1.75):
{formatted_candidates}

AUFGABE:
Wähle den stabilsten Pick mit dem höchsten Erwartungswert (+EV).
BUCHMACHER-KOMPATIBILITÄT:
- Nenne für den Pick immer eine klassische Standard-Alternative (z.B. für bet365/Tipico, falls Asian Lines fehlen).
- Weise immer eine Value-Grenze aus ('Spielbar bis @ X.XX').

Telegram-HTML ZUERST, danach der exakte JSON-Block.

REPORT-HTML:
🎯 <b>JARVIS MONEYRACE • STUFE {step} / 7</b>
Progress: [{progress_bar}] ({stake:.2f} € / {target:.2f} €)

<b>Einsatz:</b>  {stake:.2f} € (All-In)
<b>Ziel:</b>     {target:.2f} €

━━━━━━━━━━━━━━━━━━━━
📌 <b>Match:</b>   [Heim vs. Gast]
🏆 <b>Sport:</b>   [Sportart]
⏰ <b>Beginn:</b>  [Datum &amp; Uhrzeit]
🎯 <b>Tipp:</b>    <b>[Präziser Markt &amp; Auswahl]</b> @ X.XX
🔄 <b>Buchmacher-Alternative:</b> [Klassische Standard-Linie] @ X.XX
⚠️ <b>Value-Grenze:</b> Spielbar bis Mindestquote @ X.XX
💰 <b>Return:</b>  [Möglicher Return] € (+[Reingewinn] €)

━━━━━━━━━━━━━━━━━━━━
🔍 <b>EDGE &amp; QUANT-ANALYSE</b>
• <b>Modell-Chance:</b> XX.X% | <b>Fair Odds:</b> ~X.XX
• <b>Mathematischer Edge:</b> +X.X% EV
• <b>Rationale:</b> [Taktische Begründung: Matchup, Defensiv-Ratings, Form, warum das Risiko minimal ist]

━━━━━━━━━━━━━━━━━━━━
🗺️ <b>NÄCHSTER SCHRITT</b>
Bei Win geht es mit [Return] € direkt in Stufe {step + 1}.

---JSON_TRACKING---
{{
  "match": "Team A vs Team B",
  "sport": "Sportart",
  "pick": "Präziser Tipp",
  "odds": 1.65,
  "stake": {stake:.2f},
  "date": "{today_iso}"
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
            res = requests.post(url, json=payload, timeout=90)
            if res.status_code == 200:
                full_reply = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                report = full_reply
                if "---JSON_TRACKING---" in full_reply:
                    parts = full_reply.split("---JSON_TRACKING---")
                    report = parts[0].strip()
                    json_str = parts[1].replace("```json", "").replace("```", "").strip()
                    try:
                        new_bet = json.loads(json_str)
                        state["current_bet"] = new_bet
                        save_state(state)
                        print("Neue Moneyrace-Wette erfolgreich getrackt.")
                    except Exception as je:
                        print(f"Fehler beim Speichern der Moneyrace-Wette: {je}")

                report = report.replace("```html", "").replace("```", "").strip()
                send_telegram(report, pin=True)
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
    generate_moneyrace_pick()
