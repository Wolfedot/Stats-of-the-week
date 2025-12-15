from dotenv import load_dotenv
load_dotenv()

import os
import time
import sqlite3
import yaml
import requests

DB_PATH = os.getenv("DB_PATH", "stats.db")


# ---------- config + helpers ----------

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def routing_for_platform(cfg, platform):
    regions = cfg["riot"]["regions"]
    if platform not in regions:
        raise KeyError(f"Platform '{platform}' not defined in config under riot.regions")
    return regions[platform]["routing"]

def parse_riot_id(riot_id: str):
    if "#" not in riot_id:
        raise ValueError(f"riot_id must look like Name#TAG, got: {riot_id}")
    return riot_id.split("#", 1)

def riot_get(url, api_key, params=None, timeout=15, max_retries=6):
    headers = {"X-Riot-Token": api_key}
    last = None

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            last = r

            # Rate limit
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                continue

            # Transient Riot/server/proxy errors -> retry with backoff
            if r.status_code in (500, 502, 503, 504):
                # exponential-ish backoff: 2, 4, 8, 16...
                sleep_s = min(2 ** (attempt + 1), 30)
                time.sleep(sleep_s)
                continue

            r.raise_for_status()
            return r.json()

        except requests.exceptions.RequestException as e:
            # Network flake / timeout / connection reset etc.
            last = e
            sleep_s = min(2 ** (attempt + 1), 30)
            time.sleep(sleep_s)
            continue

    # If we get here, all retries failed
    if isinstance(last, requests.Response):
        last.raise_for_status()
    raise last


def get_puuid(riot_id, routing, api_key):
    name, tag = parse_riot_id(riot_id)
    url = f"https://{routing.lower()}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    return riot_get(url, api_key)["puuid"]

def enabled_queue_ids(cfg, player=None):
    src = cfg["riot"]["enabled_queues"]
    if player and player.get("overrides", {}).get("enabled_queues"):
        src = player["overrides"]["enabled_queues"]
    return {q["id"] for q in src.values()}

# ---------- DB helpers ----------

def ensure_schema(conn):
    # If the main table exists, schema is already applied
    row = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='player_match_stats'
    """).fetchone()
    if row:
        return

    # Apply schema from schema.sql
    with open("schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

def ensure_indexes(conn):
    # Optional: speed on bigger datasets
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pms_puuid_ts ON player_match_stats(puuid, game_start_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_matchid ON matches(match_id)")

def upsert_player(conn, puuid, riot_id, platform, routing):
    conn.execute(
        """
        INSERT INTO players (puuid, riot_id, platform, routing, added_at)
        VALUES (?, ?, ?, ?, unixepoch())
        ON CONFLICT(puuid) DO UPDATE SET
          riot_id = excluded.riot_id,
          platform = excluded.platform,
          routing = excluded.routing
        """,
        (puuid, riot_id, platform, routing),
    )

def get_checkpoint(conn, puuid):
    row = conn.execute(
        "SELECT last_end_time_ts FROM ingest_state WHERE puuid=?",
        (puuid,),
    ).fetchone()
    return int(row[0]) if row else None

def set_checkpoint(conn, puuid, end_ts):
    conn.execute(
        """
        INSERT INTO ingest_state (puuid, last_end_time_ts, updated_at)
        VALUES (?, ?, unixepoch())
        ON CONFLICT(puuid) DO UPDATE SET
          last_end_time_ts = excluded.last_end_time_ts,
          updated_at = unixepoch()
        """,
        (puuid, int(end_ts)),
    )

def match_exists(conn, match_id):
    row = conn.execute("SELECT 1 FROM matches WHERE match_id=? LIMIT 1", (match_id,)).fetchone()
    return row is not None

# ---------- Riot Match-v5 ----------

def get_match_ids(puuid, routing, api_key, start_time, end_time, count=100):
    url = f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"startTime": int(start_time), "endTime": int(end_time), "start": 0, "count": int(count)}
    return riot_get(url, api_key, params=params)

def get_match(match_id, routing, api_key):
    url = f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    return riot_get(url, api_key)

def find_participant(match_json, puuid):
    for p in match_json.get("info", {}).get("participants", []):
        if p.get("puuid") == puuid:
            return p
    return None

# ---------- Insert rows ----------

def insert_match_row(conn, match_id, routing, match_json):
    info = match_json.get("info", {})

    queue_id = info.get("queueId")
    game_start_ms = info.get("gameStartTimestamp")
    game_start_ts = int(game_start_ms / 1000) if isinstance(game_start_ms, (int, float)) else None

    duration_s = info.get("gameDuration")
    duration_s = int(duration_s) if isinstance(duration_s, (int, float)) else None

    game_mode = info.get("gameMode")
    game_type = info.get("gameType")
    map_id = info.get("mapId")

    conn.execute(
        """
        INSERT OR IGNORE INTO matches
        (match_id, routing, queue_id, game_start_ts, duration_s, game_mode, game_type, map_id, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, unixepoch())
        """,
        (match_id, routing, queue_id, game_start_ts, duration_s, game_mode, game_type, map_id),
    )

def insert_player_match_stats(conn, puuid, match_id, match_json):
    info = match_json.get("info", {})
    queue_id = info.get("queueId")
    game_start_ms = info.get("gameStartTimestamp")
    game_start_ts = int(game_start_ms / 1000) if isinstance(game_start_ms, (int, float)) else None

    part = find_participant(match_json, puuid)
    if not part or game_start_ts is None:
        return False

    win = 1 if part.get("win") else 0
    team_id = part.get("teamId")
    role = part.get("role")
    lane = part.get("lane")
    position = part.get("teamPosition")

    champion_id = part.get("championId")
    champion_name = part.get("championName")

    kills = int(part.get("kills", 0))
    deaths = int(part.get("deaths", 0))
    assists = int(part.get("assists", 0))

    cs = int(part.get("totalMinionsKilled", 0)) + int(part.get("neutralMinionsKilled", 0))

    gold_earned = part.get("goldEarned")
    gold_spent = part.get("goldSpent")

    dmg_to_champs = part.get("totalDamageDealtToChampions")
    dmg_taken = part.get("totalDamageTaken")

    vision_score = part.get("visionScore")
    wards_placed = part.get("wardsPlaced")
    wards_killed = part.get("wardsKilled")

    turret_kills = part.get("turretKills")

    
    raw_dead_time = part.get("totalTimeSpentDead")
    time_dead_s = int(raw_dead_time) if raw_dead_time is not None else None


    conn.execute(
        """
        INSERT OR IGNORE INTO player_match_stats (
          puuid, match_id,
          win, team_id, role, lane, position,
          champion_id, champion_name,
          kills, deaths, assists,
          cs, gold_earned, gold_spent,
          dmg_to_champs, dmg_taken,
          vision_score, wards_placed, wards_killed, turret_kills,
          time_dead_s,
          game_start_ts, queue_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            puuid, match_id,
            win, team_id, role, lane, position,
            champion_id, champion_name,
            kills, deaths, assists,
            cs, gold_earned, gold_spent,
            dmg_to_champs, dmg_taken,
            vision_score, wards_placed, wards_killed, turret_kills,
            time_dead_s,
            game_start_ts, queue_id
        ),
    )
    return True

# ---------- Main ingest ----------

def ingest(cfg, conn, api_key):
    now = int(time.time())
    lookback_days = int(cfg.get("app", {}).get("lookback_days", 7))
    default_start = now - lookback_days * 24 * 60 * 60
    max_matches = int(cfg.get("app", {}).get("max_matches_per_player", 70))

    total_new_matches = 0
    total_new_player_rows = 0
    total_skipped_by_queue = 0
    ensure_schema(conn)
    ensure_indexes(conn)

    for p in cfg.get("players", []):
        riot_id = p.get("riot_id", "?")
        match_ids = []  # so len(match_ids) is always safe

        try:
            platform = p["platform"]
            routing = routing_for_platform(cfg, platform)

            # Resolve PUUID and upsert player
            puuid = get_puuid(riot_id, routing, api_key)
            with conn:
                upsert_player(conn, puuid, riot_id, platform, routing)

            # Determine time window for this run
            checkpoint = get_checkpoint(conn, puuid)
            start_time = checkpoint if checkpoint is not None else default_start
            end_time = now

            # Pull match IDs
            match_ids = get_match_ids(
                puuid, routing, api_key,
                start_time=start_time,
                end_time=end_time,
                count=min(max_matches, 100)
            )

            enabled = enabled_queue_ids(cfg, p)

            # Process matches newest -> oldest
            for match_id in match_ids:
                if not match_exists(conn, match_id):
                    match_json = get_match(match_id, routing, api_key)
                    queue_id = match_json.get("info", {}).get("queueId")

                    if queue_id is not None and queue_id not in enabled:
                        total_skipped_by_queue += 1
                        continue

                    with conn:
                        insert_match_row(conn, match_id, routing, match_json)
                        inserted = insert_player_match_stats(conn, puuid, match_id, match_json)

                    total_new_matches += 1
                    total_new_player_rows += 1 if inserted else 0

                else:
                    row = conn.execute(
                        "SELECT 1 FROM player_match_stats WHERE puuid=? AND match_id=? LIMIT 1",
                        (puuid, match_id),
                    ).fetchone()
                    if row:
                        continue

                    match_json = get_match(match_id, routing, api_key)
                    queue_id = match_json.get("info", {}).get("queueId")
                    if queue_id is not None and queue_id not in enabled:
                        total_skipped_by_queue += 1
                        continue

                    with conn:
                        inserted = insert_player_match_stats(conn, puuid, match_id, match_json)
                    total_new_player_rows += 1 if inserted else 0

            # Update checkpoint for this player
            with conn:
                set_checkpoint(conn, puuid, end_time)

        except Exception as e:
            print(f"[ingest] ERROR for {riot_id}: {e}")
            continue

        # Update checkpoint for this player
        with conn:
            set_checkpoint(conn, puuid, end_time)

        print(f"[ingest] {riot_id}: match_ids={len(match_ids)} start={start_time} end={end_time}")

    return {
        "new_matches": total_new_matches,
        "new_player_rows": total_new_player_rows,
        "skipped_by_queue": total_skipped_by_queue,
    }

def main():
    api_key = os.getenv("RIOT_API_KEY")
    if not api_key:
        raise RuntimeError("RIOT_API_KEY not set in .env")

    cfg = load_config("config.yaml")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    stats = ingest(cfg, conn, api_key)
    conn.close()

    print("✅ Ingest complete:", stats)

if __name__ == "__main__":
    main()
