import sqlite3

conn = sqlite3.connect("stats.db")
conn.execute("ALTER TABLE player_match_stats ADD COLUMN time_dead_s INTEGER;")
conn.commit()
conn.close()

print("✅ Added time_dead_s column")