from dotenv import load_dotenv
load_dotenv()

import os
import time
import yaml
import requests

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def routing_for_platform(cfg, platform):
    return cfg["riot"]["regions"][platform]["routing"]

def riot_get(url, api_key, params=None, timeout=15):
    r = requests.get(url, headers={"X-Riot-Token": api_key}, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_puuid(riot_id, routing, api_key):
    name, tag = riot_id.split("#", 1)
    url = f"https://{routing.lower()}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    return riot_get(url, api_key)["puuid"]

def main():
    api_key = os.getenv("RIOT_API_KEY")
    if not api_key:
        raise RuntimeError("RIOT_API_KEY not set")

    cfg = load_config()
    # pick the player who played Mayhem (change index if needed)
    player = cfg["players"][0]
    riot_id = player["riot_id"]
    platform = player["platform"]
    routing = routing_for_platform(cfg, platform)

    puuid = get_puuid(riot_id, routing, api_key)

    now = int(time.time())
    start = now - 7 * 24 * 60 * 60

    ids_url = f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    match_ids = riot_get(ids_url, api_key, params={"startTime": start, "endTime": now, "start": 0, "count": 20})

    print(f"Found {len(match_ids)} matches in last 7 days for {riot_id}")
    for mid in match_ids[:10]:
        m = riot_get(f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/{mid}", api_key)
        info = m.get("info", {})
        print(
            mid,
            "queueId=", info.get("queueId"),
            "gameMode=", info.get("gameMode"),
            "gameType=", info.get("gameType"),
        )

if __name__ == "__main__":
    main()
