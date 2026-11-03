import os
import requests

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": "sportapi7.p.rapidapi.com"
}

def get_event_odds(event_id):
    """
    Holt aktuelle Quoten für ein Event über SportAPI.
    """
    if not RAPIDAPI_KEY or not event_id:
        return {}

    url = f"https://sportapi7.p.rapidapi.com/api/v1/event/{event_id}/odds"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("odds", {})
    except Exception as e:
        print(f"[Odds Scanner Error] Event {event_id}: {e}")
    return {}

def evaluate_value(calculated_prob, bookie_odds, min_edge=0.05):
    """
    Berechnet die mathematische Edge: (Prob * Odds) - 1.
    Gibt True zurück, wenn die Edge über dem Schwellenwert (z.B. 5%) liegt.
    """
    if bookie_odds <= 1.0 or calculated_prob <= 0:
        return False, 0.0

    edge = (calculated_prob * bookie_odds) - 1.0
    is_value = edge >= min_edge
    return is_value, round(edge * 100, 1)

def format_value_badge(calculated_prob, bookie_odds):
    """
    Gibt einen formatierten Textblock für die Telegram-Nachricht zurück.
    """
    is_val, edge_pct = evaluate_value(calculated_prob, bookie_odds)
    fair_odds = round(1.0 / calculated_prob, 2) if calculated_prob > 0 else 0.0

    if is_val:
        return f"💎 <b>VALUE BET (+{edge_pct}%)</b> | Fair: {fair_odds} ➔ Quote: {bookie_odds}"
    return f"Quote: {bookie_odds} (Fair: {fair_odds})"
