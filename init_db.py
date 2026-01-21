from dotenv import load_dotenv
load_dotenv()

import os
import sqlite3
from pathlib import Path

def main():
    DB_PATH = os.getenv("DB_PATH", "/data/stats.db")

    # Ensure the directory exists (important for /data/stats.db on Railway)
    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    with open("schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {db_path}")

if __name__ == "__main__":
    main()
