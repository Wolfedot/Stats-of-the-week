import sqlite3
from pathlib import Path

DB_PATH = "stats.db"
SCHEMA_PATH = "schema.sql"

def main():
    if not Path(SCHEMA_PATH).exists():
        raise FileNotFoundError("schema.sql not found")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    print("✅ Database initialized:", DB_PATH)

if __name__ == "__main__":
    main()
