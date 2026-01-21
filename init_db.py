from dotenv import load_dotenv
load_dotenv()

import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "/data/stats.db")


def main():

    # Ensure the directory exists (important for /data/stats.db on Railway)
    parent = Path(DB_PATH).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    with open("schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {DB_PATH}")

if __name__ == "__main__":
    main()
