import sqlite3

conn = sqlite3.connect("stats.db")

# total rows vs rows with time_dead_s filled
total = conn.execute("SELECT COUNT(*) FROM player_match_stats").fetchone()[0]
with_dead = conn.execute("SELECT COUNT(*) FROM player_match_stats WHERE time_dead_s IS NOT NULL").fetchone()[0]

print("player_match_stats total rows:", total)
print("rows with time_dead_s:", with_dead)

# show a few example rows that DO have it
rows = conn.execute("""
    SELECT puuid, match_id, time_dead_s, game_start_ts, queue_id
    FROM player_match_stats
    WHERE time_dead_s IS NOT NULL
    ORDER BY game_start_ts DESC
    LIMIT 10
""").fetchall()

print("\nLatest 10 rows with time_dead_s:")
for r in rows:
    print(r)

conn.close()
