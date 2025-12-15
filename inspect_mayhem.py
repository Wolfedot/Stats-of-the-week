import os, sqlite3, time

DB_PATH = os.getenv("DB_PATH", "stats.db")
start_ts = int(time.time()) - 7*24*60*60

conn = sqlite3.connect(DB_PATH)
row = conn.execute("""
SELECT COUNT(*) FROM player_match_stats
WHERE game_start_ts >= ? AND queue_id = 1700
""", (start_ts,)).fetchone()

print("queue 1700 rows last 7d:", row[0])
conn.close()