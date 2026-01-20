import sqlite3
from pathlib import Path

DB_PATH = "stats.db"

if not Path(DB_PATH).exists():
    raise FileNotFoundError("stats.db not found")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

players = conn.execute(
    "SELECT puuid, riot_id FROM players ORDER BY riot_id"
).fetchall()

print("=== Worst Game Per Player ===\n")

for p in players:
    puuid = p["puuid"]
    riot_id = p["riot_id"]

    row = conn.execute(
        """
        SELECT
          s.match_id,
          s.champion_name,
          s.kills,
          s.deaths,
          s.assists,
          s.win,
          s.queue_id,
          s.game_start_ts,
          (s.kills + s.assists) * 1.0 / NULLIF(s.deaths, 0) AS kda
        FROM player_match_stats s
        WHERE s.puuid = ?
        ORDER BY
          kda ASC,
          s.deaths DESC,
          (s.kills + s.assists) ASC
        LIMIT 1
        """,
        (puuid,),
    ).fetchone()

    if not row:
        print(f"{riot_id}: no games recorded")
        continue

    k = row["kills"]
    d = row["deaths"]
    a = row["assists"]
    kda = row["kda"]
    champ = row["champion_name"]
    result = "Win" if row["win"] else "Loss"

    kda_str = f"{kda:.2f}" if kda is not None else "∞"

    print(
        f"{riot_id}\n"
        f"  {champ} — {k}/{d}/{a} ({kda_str} KDA) — {result}\n"
    )

conn.close()
