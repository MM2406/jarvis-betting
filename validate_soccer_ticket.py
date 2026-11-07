import os
import sys
import json
import re

STATE_FILE = "pending_soccer.json"

def strip_kickoff_prefix(text):
    """Entfernt Anstoßzeit-Präfixe wie '[15:30 Uhr]' vor dem Matchnamen."""
    if not text:
        return ""
    return re.sub(r"^\s*\[\s*\d{1,2}:\d{2}(?:\s*uhr)?\s*\]\s*", "", str(text), flags=re.IGNORECASE).strip()

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

    # Wenn die Datei nach dem Settlement bereits geleert wurde ({})
    if not data or data == {}:
        print("ℹ️ State-Datei ist leer ({}) – keine offenen Wetten zu validieren.")
        sys.exit(0)

    errors = []

    # 1. POTD Validierung
    potd = data.get("potd")
    if not potd or not potd.get("match") or not potd.get("pick"):
        errors.append("POTD fehlt oder ist unvollständig.")
    else:
        potd_odds = potd.get("odds", 0)
        try:
            val = float(str(potd_odds).replace(",", "."))
            if val < 1.30 or val > 6.0:
                errors.append(f"POTD Quote unplausibel: {val}")
        except ValueError:
            errors.append(f"POTD Quote ungültig: {potd_odds}")

    # 2. Tickets & Picks prüfen
    tickets = data.get("tickets", [])
    if not tickets:
        errors.append("Keine Tickets im State-Objekt hinterlegt.")

    for ticket in tickets:
        t_name = ticket.get("ticket_name", "")
        picks = ticket.get("picks", [])

        if not picks:
            errors.append(f"Ticket '{t_name}' enthält keine Picks.")
            continue

        for pick in picks:
            match_name = strip_kickoff_prefix(pick.get("match", ""))
            pick_text = pick.get("pick", "")

            if not match_name or not pick_text:
                errors.append(f"Unvollständiger Pick in Ticket '{t_name}': {pick}")
                continue

            # Bei Player Props muss der Spieler definiert sein
            if "PLAYER" in t_name.upper():
                player = pick.get("player")
                if not player:
                    errors.append(f"Player-Prop-Pick ohne definierten Spielernamen in Ticket '{t_name}': {pick_text}")

            odds = pick.get("odds", 0)
            try:
                odds_val = float(str(odds).replace(",", "."))
                if odds_val < 1.05 or odds_val > 15.0:
                    errors.append(f"Unplausible Quote {odds_val} bei '{match_name}'.")
            except ValueError:
                errors.append(f"Ungültige Quote {odds} bei '{match_name}'.")

    # 3. Text-Prüfung
    raw_text = data.get("original_text", "")
    if raw_text and len(raw_text) < 100:
        errors.append("original_text ist verdächtig kurz (< 100 Zeichen).")

    if errors:
        print("🚨 VALIDIERUNG FEHLGESCHLAGEN! State enthält Fehler:")
        for err in errors:
            print(f"  • {err}")
        sys.exit(1)

    print("✅ VALIDIERUNG ERFOLGREICH: Alle Tickets, Quoten und Formate sind valide.")
    sys.exit(0)

if __name__ == "__main__":
    validate_state()
