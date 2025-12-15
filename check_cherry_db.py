import os, sqlite3, time

DB_PATH = os.getenv("DB_PATH", "stats.db")
start_ts = int(time.time()) - 7*24*60*60

conn = sqlite3.connect(DB_PATH)

rows = conn.execute("""
SELECT queue_id, game_mode, game_type, COUNT(*) as n
FROM matches
WHERE game_start_ts >= ?
GROUP BY queue_id, game_mode, game_type
ORDER BY n DESC
""", (start_ts,)).fetchall()

for r in rows:
    print(r)

conn.close()
