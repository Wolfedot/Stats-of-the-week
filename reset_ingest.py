import sqlite3

conn = sqlite3.connect("stats.db")
conn.execute("DELETE FROM ingest_state")
conn.commit()
conn.close()

print("✅ ingest_state cleared (one-time backfill will happen next ingest)")
