from dotenv import load_dotenv
load_dotenv()

import os
import time
import yaml
import sqlite3
import requests
conn = sqlite3.connect("stats.db")

# ---------- helpers ----------

def ensure_schema(conn):
    with open("schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def routing_for_platform(cfg, platform):
    regions = cfg["riot"]["regions"]
    if platform not in regions:
        raise KeyError(f"Platform {platform} not defined in config")
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

def enabled_queue_ids(cfg, player=None):
    src = cfg["riot"]["enabled_queues"]
    if player and player.get("overrides", {}).get("enabled_queues"):
        src = player["overrides"]["enabled_queues"]
    return {q["id"] for q in src.values()}

def get_match_ids(puuid, routing, api_key, start_time, end_time, count=50):
    url = (
        f"https://{routing.lower()}.api.riotgames.com"
        f"/lol/match/v5/matches/by-puuid/{puuid}/ids"
    )
    params = {
        "startTime": start_time,
        "endTime": end_time,
        "start": 0,
        "count": count,
    }
    return riot_get(url, api_key, params=params)

def get_match(match_id, routing, api_key):
    url = (
        f"https://{routing.lower()}.api.riotgames.com"
        f"/lol/match/v5/matches/{match_id}"
    )
    return riot_get(url, api_key)

def post_embed(webhook_url, embed):
    payload = {"embeds": [embed]}
    r = requests.post(webhook_url, json=payload, timeout=15)
    r.raise_for_status()

def find_participant(match_json, puuid):
    for p in match_json.get("info", {}).get("participants", []):
        if p.get("puuid") == puuid:
            return p
    return None

# ---------- main ----------

def main():
    
    print([row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")])
    conn.close()
    riot_key = os.getenv("RIOT_API_KEY")
    webhook_url = os.getenv("WEBHOOK_URL")

    if not riot_key:
        raise RuntimeError("RIOT_API_KEY not set")
    if not webhook_url:
        raise RuntimeError("WEBHOOK_URL not set")

    cfg = load_config("config.yaml")
    routing = routing_for_platform(cfg, platform)

    lookback_days = int(cfg.get("app", {}).get("lookback_days", 7))
    now = int(time.time())
    start_time = now - lookback_days * 24 * 60 * 60

    puuid = get_puuid(riot_id, routing, riot_key)

    cap = int(cfg.get("app", {}).get("max_matches_per_player", 50))
    match_ids = get_match_ids(puuid, routing, riot_key, start_time, now, count=min(cap, 100))

    newest_match_summary = "No matches found in the last 7 days."
    newest_queue_summary = "-"
    newest_enabled_summary = "-"

    if match_ids:
        match_json = get_match(match_ids[0], routing, riot_key)
        info = match_json.get("info", {})

        queue_id = info.get("queueId")
        game_mode = info.get("gameMode")
        game_type = info.get("gameType")
        duration = info.get("gameDuration")
        duration_min = duration / 60 if isinstance(duration, (int, float)) else None

        part = find_participant(match_json, puuid)
        if part:
            champ = part.get("championName", "Unknown")
            win = "Win" if part.get("win") else "Loss"
            k, d, a = part.get("kills", 0), part.get("deaths", 0), part.get("assists", 0)
            newest_match_summary = f"{champ} — {win} — {k}/{d}/{a}"

        newest_queue_summary = f"queueId {queue_id} | {game_mode} | {game_type}"
        if duration_min:
            newest_queue_summary += f" | {duration_min:.1f}m"

        newest_enabled_summary = (
            "✅ Included"
            if queue_id in enabled_queue_ids(cfg, player)
            else "❌ Filtered out"
        )

    embed = {
        "title": "✅ Riot Match-v5 Test",
        "description": "Fetched recent matches and inspected the newest one.",
        "fields": [
            {"name": "Player", "value": f"{riot_id} ({platform}/{routing})", "inline": False},
            {"name": "Matches found", "value": str(len(match_ids)), "inline": True},
            {"name": "Enabled queues", "value": ", ".join(map(str, sorted(enabled_queue_ids(cfg, player)))), "inline": True},
            {"name": "Newest match (stats)", "value": newest_match_summary, "inline": False},
            {"name": "Newest match (queue)", "value": newest_queue_summary, "inline": False},
            {"name": "Counted?", "value": newest_enabled_summary, "inline": False},
        ],
    }

    post_embed(webhook_url, embed)
    print("Match-v5 test payload sent.")

if __name__ == "__main__":
    main()
