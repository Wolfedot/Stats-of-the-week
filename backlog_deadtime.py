from dotenv import load_dotenv
load_dotenv()

import os
import time
import sqlite3
import requests

DB_PATH = os.getenv("DB_PATH", "stats.db")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")

if not RIOT_API_KEY:
    raise RuntimeError("RIOT_API_KEY not set")

def riot_get(url):
    r = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY}, timeout=20)
    if r.status_code == 429:
        # basic rate limit handling
        time.sleep(int(r.headers.get("Retry-After", "2")))
        return riot_get(url)
    r.raise_for_status()
    return r.json()

LOOKBACK_DAYS = 7
start_ts = int(time.time()) - LOOKBACK_DAYS * 24 * 60 * 60

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
SELECT s.puuid, s.match_id, m.routing
FROM player_match_stats s
JOIN matches m ON m.match_id = s.match_id
WHERE s.game_start_ts >= ?
  AND s.time_dead_s IS NULL
ORDER BY s.game_start_ts DESC
""", (start_ts,)).fetchall()

print("Rows to backfill:", len(rows))

updated = 0
for i, row in enumerate(rows, start=1):
    puuid = row["puuid"]
    match_id = row["match_id"]
    routing = row["routing"]

    match = riot_get(f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/{match_id}")

    part = None
    for p in match["info"]["participants"]:
        if p.get("puuid") == puuid:
            part = p
            break

    if not part:
        continue

    raw = part.get("totalTimeSpentDead")
    if raw is None:
        continue

    conn.execute(
        "UPDATE player_match_stats SET time_dead_s = ? WHERE puuid = ? AND match_id = ?",
        (int(raw), puuid, match_id),
    )
    updated += 1

    # commit every 50 updates
    if updated % 50 == 0:
        conn.commit()
        print(f"Updated {updated}/{len(rows)}...")

conn.commit()
conn.close()

print(f"✅ Backfill done. Updated rows: {updated}")
