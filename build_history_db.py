import os
import sqlite3
import pandas as pd
import requests
from io import StringIO

DB_FILE = "jarvis_matches.db"

# Ligen-Codes von football-data.co.uk:
# E0 = Premier League, D1 = Bundesliga, I1 = Serie A, SP1 = La Liga, F1 = Ligue 1
LEAGUES = ["E0", "D1", "I1", "SP1", "F1"]

# Saisons: z.B. 2122 (2021/22), 2223 (2022/23), 2324 (2023/24), 2425 (2024/25)
SEASONS = ["2223", "2324", "2425", "2526"]

BASE_URL = "https://www.football-data.co.uk/mmz4281"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            season TEXT,
            league TEXT,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            fthg INTEGER,
            ftag INTEGER,
            ftr TEXT,
            hthg INTEGER,
            htag INTEGER,
            home_shots INTEGER,
            away_shots INTEGER,
            home_shots_target INTEGER,
            away_shots_target INTEGER,
            odds_b365_home REAL,
            odds_b365_draw REAL,
            odds_b365_away REAL,
            odds_b365_over25 REAL,
            odds_b365_under25 REAL
        )
    """)
    conn.commit()
    conn.close()

def clean_column(df, col_name, default_val=None):
    if col_name in df.columns:
        return df[col_name]
    return default_val

def fetch_and_store():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    total_inserted = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    print("🚀 Starte Download und Aufbau der SQLite-Datenbank...")

    for season in SEASONS:
        for league in LEAGUES:
            url = f"{BASE_URL}/{season}/{league}.csv"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code != 200:
                    continue

                csv_text = res.content.decode("utf-8", errors="replace")
                df = pd.read_csv(StringIO(csv_text))

                # Relevante Spalten filtern
                required_cols = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
                if not all(col in df.columns for col in required_cols):
                    continue

                # Leere Zeilen entfernen
                df = df.dropna(subset=required_cols)

                for _, row in df.iterrows():
                    h_team = str(row["HomeTeam"]).strip()
                    a_team = str(row["AwayTeam"]).strip()
                    m_date = str(row["Date"]).strip()

                    match_id = f"{season}_{league}_{m_date}_{h_team}_{a_team}".replace(" ", "_")

                    # Schüsse und Quoten sicher extrahieren
                    hs = row.get("HS") if pd.notnull(row.get("HS")) else None
                    as_shots = row.get("AS") if pd.notnull(row.get("AS")) else None
                    hst = row.get("HST") if pd.notnull(row.get("HST")) else None
                    ast = row.get("AST") if pd.notnull(row.get("AST")) else None
                    
                    b365_h = row.get("B365H") if pd.notnull(row.get("B365H")) else None
                    b365_d = row.get("B365D") if pd.notnull(row.get("B365D")) else None
                    b365_a = row.get("B365A") if pd.notnull(row.get("B365A")) else None
                    b365_o25 = row.get("B365>2.5") if pd.notnull(row.get("B365>2.5")) else None
                    b365_u25 = row.get("B365<2.5") if pd.notnull(row.get("B365<2.5")) else None

                    cursor.execute("""
                        INSERT OR REPLACE INTO matches (
                            match_id, season, league, match_date, home_team, away_team,
                            fthg, ftag, ftr, hthg, htag,
                            home_shots, away_shots, home_shots_target, away_shots_target,
                            odds_b365_home, odds_b365_draw, odds_b365_away,
                            odds_b365_over25, odds_b365_under25
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        match_id, season, league, m_date, h_team, a_team,
                        int(row["FTHG"]), int(row["FTAG"]), str(row.get("FTR", "")),
                        int(row["HTHG"]) if pd.notnull(row.get("HTHG")) else None,
                        int(row["HTAG"]) if pd.notnull(row.get("HTAG")) else None,
                        int(hs) if hs is not None else None,
                        int(as_shots) if as_shots is not None else None,
                        int(hst) if hst is not None else None,
                        int(ast) if ast is not None else None,
                        float(b365_h) if b365_h is not None else None,
                        float(b365_d) if b365_d is not None else None,
                        float(b365_a) if b365_a is not None else None,
                        float(b365_o25) if b365_o25 is not None else None,
                        float(b365_u25) if b365_u25 is not None else None
                    ))
                    total_inserted += 1

                print(f"✔ {league} ({season}): {len(df)} Spiele importiert.")
            except Exception as e:
                print(f"Fehler bei {league} ({season}): {e}")

    conn.commit()
    conn.close()
    print(f"\n🎉 Fertig! Insgesamt wurden {total_inserted} Datensätze in '{DB_FILE}' eingepflegt.")

if __name__ == "__main__":
    init_db()
    fetch_and_store()
