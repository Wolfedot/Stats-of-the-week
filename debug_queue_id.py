from dotenv import load_dotenv
load_dotenv()

import os, time, requests, yaml

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)



def riot_get(url, api_key, params=None):
    r = requests.get(url, headers={"X-Riot-Token": api_key}, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

cfg = load_config()
api_key = os.getenv("RIOT_API_KEY")
if not api_key:
    raise RuntimeError("RIOT_API_KEY not set")



# pick first player from config
p = cfg["players"][0]
riot_id = p["riot_id"]
platform = p["platform"]
routing = cfg["riot"]["regions"][platform]["routing"]

name, tag = riot_id.split("#", 1)
acct = riot_get(f"https://{routing.lower()}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}", api_key)
puuid = acct["puuid"]

start_ts = int(time.time()) - 7*24*60*60

# IMPORTANT: pull MORE than your cap using count=100
ids = riot_get(
    f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids",
    api_key,
    params={"startTime": start_ts, "count": 100}
)

print("match ids returned:", len(ids))

# check queueIds by fetching a few matches
for mid in ids[:25]:
    m = riot_get(f"https://{routing.lower()}.api.riotgames.com/lol/match/v5/matches/{mid}", api_key)
    info = m["info"]
    print(mid, "queueId=", info.get("queueId"), "gameMode=", info.get("gameMode"), "gameType=", info.get("gameType"))
