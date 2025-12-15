import os, sqlite3
DB_PATH = os.getenv("DB_PATH", "stats.db")
conn = sqlite3.connect(DB_PATH)
n = conn.execute("SELECT COUNT(*) FROM ingest_state").fetchone()[0]
print("ingest_state rows:", n)
conn.close()