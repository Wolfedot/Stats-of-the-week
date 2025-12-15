from dotenv import load_dotenv
load_dotenv()

import os
import time
import sqlite3
import yaml
import requests

DB_PATH = "stats.db"

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

def riot_get(url, api_key, params=None, timeout=15, max_retries=3):
    headers = {"X-Riot-Token": api_key}
    for _ in range(max_retries):
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "2"))
            time.sleep(retry_after)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()

def get_puuid(riot_id, routing, api_key):
    name, tag = parse_riot_id(riot_id)
    url = (
        f"https://{routing.lower()}.api.riotgames.com"
        f"/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    )
    return riot_get(url, api_key)["puuid"]

def sync_players(cfg, conn, api_key):
    """
    Ensures every player in config.yaml exists in the DB.
    Inserts new players and updates riot_id/platform/routing for existing puuids.
    Returns a list of (riot_id, puuid, platform, routing).
    """
    results = []

    # Good practice: wrap changes in a transaction
    with conn:
        for p in cfg.get("players", []):
            riot_id = p["riot_id"]
            platform = p["platform"]
            routing = routing_for_platform(cfg, platform)

            puuid = get_puuid(riot_id, routing, api_key)

            # Insert or update by puuid (primary key)
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

            results.append((riot_id, puuid, platform, routing))

    return results

def main():
    riot_key = os.getenv("RIOT_API_KEY")
    if not riot_key:
        raise RuntimeError("RIOT_API_KEY not set in .env")

    cfg = load_config("config.yaml")
    conn = sqlite3.connect(DB_PATH)

    rows = sync_players(cfg, conn, riot_key)

    print("✅ Synced players:")
    for riot_id, puuid, platform, routing in rows:
        print(f" - {riot_id} | {platform}/{routing} | {puuid}")

    conn.close()

if __name__ == "__main__":
    main()
