import sqlite3

conn = sqlite3.connect("stats.db")
rows = conn.execute("""
    SELECT queue_id, COUNT(*) AS games
    FROM matches
    GROUP BY queue_id
    ORDER BY games DESC
""").fetchall()

for qid, games in rows:
    print(qid, games)

conn.close()
