import os
import sys
import json
import time
import requests
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ==========================================
# KONFIGURATION & CREDENTIALS
# ==========================================
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

# ==========================================
# STATE & TELEGRAM HILFSFUNKTIONEN
# ==========================================
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
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Fehler beim Laden von {PENDING_FILE}: {e}")
        return []

def save_pending(pending_list):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von {PENDING_FILE}: {e}")

# ==========================================
# 1. MORGEN-SETTLEMENT (ABRECHNUNG & KOMBI-LEGS)
# ==========================================
def settle_pending_bets():
    pending = load_pending()
    if not pending:
        print("Keine offenen Wetten in pending_nhl.json gefunden.")
        return

    print(f"Prüfe Abrechnung für {len(pending)} offene NHL-Picks...")
    remaining_pending = []
    settled_results = []

    for bet in pending:
        match = bet.get("match", "")
        pick = bet.get("pick", "")
        odds = bet.get("odds", "-")
        date_str = bet.get("date", "")
        is_kombi = bet.get("is_kombi", False) or "kombi" in bet.get("category", "").lower() or "+" in pick

        prompt = f"""
Du bist ein Sport-Abrechnungssystem für Eishockey (NHL).
Ermittle via Google Search die offiziellen Endergebnisse für folgende NHL-Wette:
- Spiel / Begegnungen: {match}
- Datum: {date_str}
- Wette: {pick}
- Ist Kombiwette: {is_kombi}

REGELN FÜR NHL:
- Alle Torwetten und Sieger gelten inklusive Overtime (OT) und Shootout (SO), sofern nicht anders angegeben.
- Tore und Assists ergeben Scorerpunkte.

AUFGABE:
1. Prüfe, ob alle relevanten Spiele offiziell beendet sind (FINAL).
2. Falls eine Kombiwette vorliegt:
   - Werte jedes einzelne Bein (Leg) separat aus.
   - Wenn alle Beine gewonnen sind -> RESULT: WON
   - Wenn mindestens ein Bein verloren ist -> RESULT: LOST
   - Gib für jedes Bein das exakte Ergebnis und den Status an.
3. Falls Einzelwette: Ermittle Endstand und bewerte WON oder LOST.
4. Falls Spiele noch laufen oder ausstehen -> STATUS: PENDING

Antworte STRIKT in diesem Format:
STATUS: FINISHED oder PENDING
RESULT: WON oder LOST oder PENDING
LEGS_WON: Anzahl der gewonnenen Beine (z.B. 2 bei Kombi, sonst 1 wenn WON, 0 wenn LOST)
LEGS_TOTAL: Gesamtanzahl der Beine (z.B. 3 bei 3er-Kombi, 1 bei Single)
DETAILS:
- Bein 1: Team A vs Team B | Ergebnis: X:Y | WON oder LOST
- Bein 2: ...
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.1}
        }

        try:
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                ans = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                status = "PENDING"
                result = "PENDING"
                legs_won = 0
                legs_total = 1
                details_lines = []
                in_details = False

                for line in ans.split("\n"):
                    line_s = line.strip()
                    if line_s.startswith("STATUS:"):
                        status = line_s.replace("STATUS:", "").strip().upper()
                    elif line_s.startswith("RESULT:"):
                        result = line_s.replace("RESULT:", "").strip().upper()
                    elif line_s.startswith("LEGS_WON:"):
                        try:
                            legs_won = int(line_s.replace("LEGS_WON:", "").strip())
                        except ValueError:
                            pass
                    elif line_s.startswith("LEGS_TOTAL:"):
                        try:
                            legs_total = int(line_s.replace("LEGS_TOTAL:", "").strip())
                        except ValueError:
                            pass
                    elif line_s.startswith("DETAILS:"):
                        in_details = True
                    elif in_details and line_s:
                        details_lines.append(line_s)

                if status == "FINISHED" and result in ["WON", "LOST"]:
                    try:
                        odds_val = float(str(odds).replace(",", "."))
                    except ValueError:
                        odds_val = 1.0

                    stake = 1.0
                    pnl = (stake * odds_val - stake) if result == "WON" else -stake

                    if not is_kombi:
                        legs_total = 1
                        legs_won = 1 if result == "WON" else 0

                    settled_results.append({
                        "match": match,
                        "pick": pick,
                        "odds": odds,
                        "odds_val": odds_val,
                        "stake": stake,
                        "pnl": pnl,
                        "result": result,
                        "is_kombi": is_kombi,
                        "legs_won": legs_won,
                        "legs_total": legs_total,
                        "details": details_lines
                    })
                else:
                    remaining_pending.append(bet)
            else:
                remaining_pending.append(bet)
        except Exception as e:
            print(f"Fehler bei NHL-Settlement für {match}: {e}")
            remaining_pending.append(bet)

    save_pending(remaining_pending)

    if settled_results:
        # Aufteilung in Singles und Kombis
        singles = [b for b in settled_results if not b["is_kombi"]]
        kombis = [b for b in settled_results if b["is_kombi"]]

        singles_won = sum(1 for b in singles if b["result"] == "WON")
        kombis_won = sum(1 for b in kombis if b["result"] == "WON")

        total_staked = sum(b["stake"] for b in settled_results)
        total_pnl = sum(b["pnl"] for b in settled_results)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        pnl_sign = "+" if total_pnl >= 0 else ""

        kombi_legs_won = sum(b["legs_won"] for b in kombis)
        kombi_legs_total = sum(b["legs_total"] for b in kombis)

        total_picks_count = len(singles) + kombi_legs_total
        total_picks_won = singles_won + kombi_legs_won
        overall_accuracy = (total_picks_won / total_picks_count * 100) if total_picks_count > 0 else 0

        # Nachricht erstellen
        msg = "🏒 <b>JARVIS NHL SETTLEMENT & RECAP</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for b in settled_results:
            icon = "✅" if b["result"] == "WON" else "❌"
            pnl_str = f"+{b['pnl']:.2f}u" if b["pnl"] >= 0 else f"{b['pnl']:.2f}u"

            if b["is_kombi"]:
                msg += f"{icon} <b>Kombi: {b['pick']} @ {b['odds']}</b>\n"
                msg += f"• <b>Status:</b> {b['result']} ({pnl_str})\n"
                msg += f"• <b>Beine getroffen:</b> {b['legs_won']}/{b['legs_total']}\n"
                if b["details"]:
                    for d in b["details"]:
                        msg += f"  {d}\n"
            else:
                msg += f"{icon} <b>{b['match']}</b>\n"
                msg += f"• <b>Pick:</b> {b['pick']} @ {b['odds']}\n"
                msg += f"• <b>Status:</b> {b['result']} ({pnl_str})\n"
                if b["details"]:
                    for d in b["details"]:
                        msg += f"• <i>{d}</i>\n"

            msg += "━━━━━━━━━━━━━━━━━━━━\n"

        # Detaillierter Statistik-Block
        msg += "📊 <b>BILANZ & STATISTIK</b>\n"
        if singles:
            s_pnl = sum(b["pnl"] for b in singles)
            s_sign = "+" if s_pnl >= 0 else ""
            msg += f"• <b>Single Bets:</b> {singles_won}/{len(singles)} ({(singles_won/len(singles)*100):.1f}%) | {s_sign}{s_pnl:.2f}u\n"
        if kombis:
            k_pnl = sum(b["pnl"] for b in kombis)
            k_sign = "+" if k_pnl >= 0 else ""
            msg += f"• <b>Kombiwetten:</b> {kombis_won}/{len(kombis)} ({(kombis_won/len(kombis)*100):.1f}%) | {k_sign}{k_pnl:.2f}u\n"
            msg += f"• <b>Kombi-Beine (Legs):</b> {kombi_legs_won}/{kombi_legs_total} ({(kombi_legs_won/kombi_legs_total*100):.1f}%)\n"

        msg += "────────────────────\n"
        msg += f"• <b>Gesamttreffer (inkl. Legs):</b> {total_picks_won}/{total_picks_count} ({overall_accuracy:.1f}%)\n"
        msg += f"• <b>Gesamtertrag (Flat 1u):</b> <b>{pnl_sign}{total_pnl:.2f} Units</b>\n"
        msg += f"• <b>ROI:</b> <b>{pnl_sign}{roi:.1f}%</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"

        send_telegram(msg)
        print("NHL Settlement mit voller Statistik erfolgreich gesendet.")

# ==========================================
# 2. ODDS API & PICKS GENERIERUNG
# ==========================================
def fetch_nhl_odds():
    url = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,totals",
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
    odds_data = fetch_nhl_odds()
    if not odds_data:
        print("Keine NHL-Spiele im Zeitfenster gefunden.")
        return

    today_str = datetime.now(LOCAL_TZ).strftime("%d.%m.%Y")
    today_iso = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    prompt = f"""
Du bist 'JARVIS NHL QUANT' – Spezialist für quantitative NHL-Modellierung, Goalie-Matchups und Quoten-Diskrepanzen.
Erstelle für heute ({today_str}) das NHL-Dossier.

VERFÜGBARE PARTIEN & ECHTE BUCHMACHERQUOTEN:
{odds_data}

REGELN:
- Wähle ausschließlich Partien aus der obigen Liste.
- WICHTIG: Es handelt sich um Eishockey (NHL) – Tore und Assists ergeben Punkte.
- Analysiere Starting Goalies (Confirmed/Expected), Special Teams (PP%/PK%), Corsi/Fenwick und Rest Advantage via Google Search.
- Erstelle 1x Pick of the Day, 1x Value Acca (Kombi mit 2-4 Spielen), 1x Totals Spotlight und 1x Player Prop (Punkte/Tore/Schüsse).

FORMATIERUNGS-REGELN FÜR TELEGRAM:
- Keine doppelten Leerzeilen.
- Beginne jede Aufzählung direkt mit '• ' (Unicode Bullet) OHNE Zeilenumbruch nach dem Bullet!
- Schreibe Pfeile direkt vor den Text: '➔ <b>Haupt-Pick:</b> ...' OHNE Leerzeile davor.
- Ganz am Ende MUSS der exakte Parser-Block '---JSON_TRACKING---' folgen.

---JSON_TRACKING---
[
  {{
    "match": "Team A vs Team B",
    "sport": "NHL",
    "category": "PICK OF THE DAY",
    "pick": "Team A Sieg (inkl. OT)",
    "odds": "1.85",
    "date": "{today_iso}",
    "is_kombi": false
  }},
  {{
    "match": "BOS vs CHI / NSH vs TBL",
    "sport": "NHL",
    "category": "QUANT VALUE ACCA",
    "pick": "Bruins ML + Lightning ML",
    "odds": "2.80",
    "date": "{today_iso}",
    "is_kombi": true
  }}
]
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
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
                        print(f"Fehler beim Parsen der NHL-Picks: {je}")

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

# ==========================================
# 3. HAUPTSTEUERUNG MIT ZEIT-WEICHE
# ==========================================
def main():
    now_berlin = datetime.now(LOCAL_TZ)
    current_hour = now_berlin.hour

    print(f"=== JARVIS NHL ENGINE START [{now_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}] ===")

    # 1. Abrechnung läuft morgens wie abends immer
    settle_pending_bets()

    # 2. Picks nur ab 16:00 Uhr MEZ generieren (Goalie-Confirmations abwarten)
    if current_hour >= 16:
        print(f"Abend-Fenster aktiv ({current_hour} Uhr MEZ): Generiere neues NHL-Dossier...")
        run_nhl_intel()
    else:
        print(f"Morgen-Fenster aktiv ({current_hour} Uhr MEZ): Nur Abrechnung ausgeführt. Picks folgen abends.")

if __name__ == "__main__":
    main()
