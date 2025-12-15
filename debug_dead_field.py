from dotenv import load_dotenv
load_dotenv()

import os, sqlite3, requests, time

DB_PATH = os.getenv("DB_PATH", "stats.db")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")

if not RIOT_API_KEY:
    raise RuntimeError("RIOT_API_KEY not set")

def riot_get(url):
    r = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY}, timeout=20)
    r.raise_for_status()
    return r.json()

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# pick a player with lots of NULLs
puuid = conn.execute("SELECT puuid FROM players WHERE riot_id=?", ("Mag1c#1204",)).fetchone()["puuid"]

# get a recent match id for them from your DB
row = conn.execute("""
SELECT s.match_id, m.routing
FROM player_match_stats s
JOIN matches m ON m.match_id = s.match_id
WHERE s.puuid=? AND s.time_dead_s IS NULL
ORDER BY s.game_start_ts DESC
LIMIT 1
""", (puuid,)).fetchone()

match_id = row["match_id"]
routing = row["routing"]
conn.close()

print("Testing match:", match_id, "routing:", routing)

match = riot_get(f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/{match_id}")

# find the participant again
part = None
for p in match["info"]["participants"]:
    if p.get("puuid") == puuid:
        part = p
        break

print("Found participant:", part is not None)
print("Keys containing 'dead':", [k for k in part.keys() if "dead" in k.lower()])
print("totalTimeSpentDead value:", part.get("totalTimeSpentDead"))
print("deaths:", part.get("deaths"))
