import os, sqlite3

DB_PATH = os.getenv("DB_PATH", "stats.db")

conn = sqlite3.connect(DB_PATH)
conn.execute("DELETE FROM ingest_state;")
conn.commit()
conn.close()

print("✅ ingest_state cleared from", DB_PATH)
