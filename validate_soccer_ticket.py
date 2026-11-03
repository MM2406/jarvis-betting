import os
import sys
import json
import re

STATE_FILE = "pending_soccer.json"

def validate_state():
    if not os.path.exists(STATE_FILE):
        print(f"❌ FEHLER: {STATE_FILE} nicht gefunden.")
        sys.exit(1)

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ FEHLER: JSON-Parsing fehlgeschlagen: {e}")
        sys.exit(1)

    errors = []

    # 1. Player Props Verbot (Sofort-Filter gegen falsche Spieler/Kader)
    for ticket in data.get("tickets", []):
        t_name = ticket.get("ticket_name", "").upper()
        if "PLAYER" in t_name or "PROP" in t_name:
            errors.append(f"Ticket '{ticket.get('ticket_name')}' ist ein Player-Prop-Ticket. Spielerwetten sind aktuell deaktiviert!")

        for pick in ticket.get("picks", []):
            if "player" in pick:
                errors.append(f"Pick enthält 'player': {pick.get('player')}. Einzelspieler-Picks sind gesperrt!")
            
            p_text = pick.get("pick", "").lower()
            if any(k in p_text for k in ["schuss", "torschuss", "sot", "spieler"]):
                errors.append(f"Pick '{pick.get('pick')}' enthält verdächtige Spieler-Metriken!")

            odds = pick.get("odds", 0)
            try:
                odds_val = float(odds)
                if odds_val < 1.05 or odds_val > 15.0:
                    errors.append(f"Unplausible Quote {odds_val} bei {pick.get('match')}.")
            except ValueError:
                errors.append(f"Ungültige Quote {odds} bei {pick.get('match')}.")

    # 2. POTD Validierung
    potd = data.get("potd")
    if not potd or not potd.get("match") or not potd.get("pick"):
        errors.append("POTD fehlt oder ist unvollständig.")

    # 3. Text-Plausibilitätsprüfung
    raw_text = data.get("original_text", "")
    forbidden_terms = ["player prop", "torschuss", "lewandowski"]
    for term in forbidden_terms:
        if term in raw_text.lower():
            errors.append(f"Unzulässiger Begriff '{term}' im original_text gefunden!")

    if errors:
        print("🚨 VALIDIERUNG FEHLGESCHLAGEN! POST WURDE BLOCKIERT:")
        for err in errors:
            print(f"  • {err}")
        sys.exit(1)

    print("✅ VALIDIERUNG ERFOLGREICH: Keine gesperrten Kategorien oder unplausiblen Quoten gefunden.")
    sys.exit(0)

if __name__ == "__main__":
    validate_state()
