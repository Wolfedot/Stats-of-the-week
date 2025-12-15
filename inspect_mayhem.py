import sqlite3
import time

DB_PATH = "stats.db"
MAYHEM_QUEUE = 1700
LOOKBACK_DAYS = 7

now = int(time.time())
start_ts = now - LOOKBACK_DAYS * 24 * 60 * 60

conn = sqlite3