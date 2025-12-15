# check_dead_coverage.py
import os, sqlite3, time
DB_PATH = os.getenv("DB_PATH", "stats.db")
start_ts = int(time.time()) - 7*24*60*60

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
SELECT p.riot_id,
       COUNT(*) AS total,
       SUM(CASE WHEN s.time_dead_s IS NOT NULL THEN 1 ELSE 0 END) AS filled
FROM player_match_stats s
JOIN players p ON p.puuid = s.puuid
WHERE s.game_start_ts >= ?
GROUP BY p.riot_id
ORDER BY total DESC;
""", (start_ts,)).fetchall()

for r in rows:
    print(f"{r['riot_id']}: {r['filled']}/{r['total']} filled")

conn.close()