import sqlite3
import math
import sys

DB_FILE = "jarvis_matches.db"

def poisson_pmf(k, lamb):
    """Wahrscheinlichkeit für exakt k Ereignisse bei Erwartungswert lamb."""
    if lamb <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

def get_team_stats(cursor, team_name, limit=20):
    """Holt die letzten Spiele eines Teams und berechnet Tor-Mittelwerte."""
    # Heimspiele
    cursor.execute("""
        SELECT fthg, ftag FROM matches 
        WHERE home_team LIKE ? 
        ORDER BY rowid DESC LIMIT ?
    """, (f"%{team_name}%", limit))
    home_matches = cursor.fetchall()

    # Auswärtsspiele
    cursor.execute("""
        SELECT ftag, fthg FROM matches 
        WHERE away_team LIKE ? 
        ORDER BY rowid DESC LIMIT ?
    """, (f"%{team_name}%", limit))
    away_matches = cursor.fetchall()

    total_matches = len(home_matches) + len(away_matches)
    if total_matches == 0:
        return None

    scored = sum(m[0] for m in home_matches) + sum(m[0] for m in away_matches)
    conceded = sum(m[1] for m in home_matches) + sum(m[1] for m in away_matches)

    return {
        "matches": total_matches,
        "avg_scored": scored / total_matches,
        "avg_conceded": conceded / total_matches
    }

def calculate_match_odds(home_team, away_team):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    h_stats = get_team_stats(cursor, home_team)
    a_stats = get_team_stats(cursor, away_team)
    conn.close()

    if not h_stats or not a_stats:
        return None

    # Einfache Poisson-Torerwartung (Attack vs. Defense unter Berücksichtigung eines leichten Heimvorteils)
    lambda_home = (h_stats["avg_scored"] + a_stats["avg_conceded"]) / 2.0 * 1.08
    lambda_away = (a_stats["avg_scored"] + h_stats["avg_conceded"]) / 2.0 * 0.92

    # Score-Matrix berechnen (bis maximal 6 Tore pro Team)
    p_home_win = 0.0
    p_draw = 0.0
    p_away_win = 0.0
    p_over25 = 0.0
    p_btts = 0.0

    for h in range(7):
        for a in range(7):
            p = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
            
            if h > a:
                p_home_win += p
            elif h == a:
                p_draw += p
            else:
                p_away_win += p

            if h + a > 2.5:
                p_over25 += p

            if h > 0 and a > 0:
                p_btts += p

    return {
        "home_team": home_team,
        "away_team": away_team,
        "lambda_home": round(lambda_home, 2),
        "lambda_away": round(lambda_away, 2),
        "probs": {
            "home_win": round(p_home_win * 100, 1),
            "draw": round(p_draw * 100, 1),
            "away_win": round(p_away_win * 100, 1),
            "over_25": round(p_over25 * 100, 1),
            "btts": round(p_btts * 100, 1)
        },
        "fair_odds": {
            "home_win": round(1.0 / p_home_win, 2) if p_home_win > 0 else 99.0,
            "draw": round(1.0 / p_draw, 2) if p_draw > 0 else 99.0,
            "away_win": round(1.0 / p_away_win, 2) if p_away_win > 0 else 99.0,
            "over_25": round(1.0 / p_over25, 2) if p_over25 > 0 else 99.0,
            "btts": round(1.0 / p_btts, 2) if p_btts > 0 else 99.0
        }
    }

if __name__ == "__main__":
    # Test-Aufruf direkt über die Konsole oder Testdaten
    h = sys.argv[1] if len(sys.argv) > 1 else "Liverpool"
    a = sys.argv[2] if len(sys.argv) > 2 else "Chelsea"

    res = calculate_match_odds(h, a)
    if res:
        print(f"📊 Quant-Analyse: {res['home_team']} vs. {res['away_team']}")
        print(f"  • Torerwartung (xG): {res['lambda_home']} zu {res['lambda_away']}")
        print(f"  • Wahrscheinlichkeiten: Heim: {res['probs']['home_win']}% | Remis: {res['probs']['draw']}% | Auswärts: {res['probs']['away_win']}%")
        print(f"  • Über 2.5 Tore: {res['probs']['over_25']}% (Fair: @{res['fair_odds']['over_25']})")
        print(f"  • BTTS (Beide treffen): {res['probs']['btts']}% (Fair: @{res['fair_odds']['btts']})")
    else:
        print(f"Keine ausreichenden Daten für {h} vs. {a} in der DB gefunden.")
