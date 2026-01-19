from dotenv import load_dotenv, find_dotenv
import os

dotenv_path = find_dotenv()
print("Loaded .env from:", dotenv_path or "(none found)")
load_dotenv(dotenv_path, override=True)  # IMPORTANT: override=True
print("WEBHOOK_URL =", os.getenv("WEBHOOK_URL"))


import time
import sqlite3
import yaml
import requests

DB_PATH = os.getenv("DB_PATH", "stats.db")


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def discord_mention_for_riot_id(cfg, riot_id: str) -> str:
    for p in cfg.get("players", []):
        if p.get("riot_id") == riot_id and p.get("discord_id"):
            return f"<@{p['discord_id']}>"
    return riot_id  # fallback if missing

def enabled_queue_ids(cfg, player=None):
    src = cfg["riot"]["enabled_queues"]
    if player and player.get("overrides", {}).get("enabled_queues"):
        src = player["overrides"]["enabled_queues"]
    return {q["id"] for q in src.values()}


def queue_ids_excluding_labels(cfg, excluded_prefixes):
    """
    Returns enabled queue IDs excluding any whose label starts with a prefix
    in excluded_prefixes (case-insensitive).
    """
    out = []
    for q in cfg["riot"]["enabled_queues"].values():
        label = (q.get("label") or "").lower().strip()
        if any(label.startswith(p.lower()) for p in excluded_prefixes):
            continue
        out.append(int(q["id"]))
    return sorted(set(out))

def queue_ids_including_labels(cfg, included_prefixes):
    """
    Returns enabled queue IDs including only those whose label starts with a prefix
    in included_prefixes (case-insensitive).
    """
    out = []
    for q in cfg["riot"]["enabled_queues"].values():
        label = (q.get("label") or "").lower().strip()
        if any(label.startswith(p.lower()) for p in included_prefixes):
            out.append(int(q["id"]))
    return sorted(set(out))



def post_embeds(webhook_url, embeds):
    payload = {
        "embeds": embeds,
        "allowed_mentions": {"parse": ["users"]},
    }
    r = requests.post(webhook_url, json=payload, timeout=15)
    r.raise_for_status()

def kda_ratio(k, d, a):
    d = int(d or 0)
    if d == 0:
        return float(int(k or 0) + int(a or 0))
    return (int(k or 0) + int(a or 0)) / d

def compute_weekly_cs_per_min(conn, start_ts, enabled_queues, min_duration_s=600):
    """
    For each riot_id, compute avg CS/min over the time window.
    Joins player_match_stats to matches to use match duration.
    Filters out very short games (< min_duration_s) to ignore remakes.
    """
    if not enabled_queues:
        return {}

    placeholders = ",".join("?" for _ in enabled_queues)
    params = [start_ts, *enabled_queues, min_duration_s]

    rows = conn.execute(
        f"""
        SELECT
          p.riot_id AS riot_id,
          COUNT(*) AS games,
          AVG(1.0 * s.cs / (m.duration_s / 60.0)) AS avg_cs_min
        FROM player_match_stats s
        JOIN matches m ON m.match_id = s.match_id
        JOIN players p ON p.puuid = s.puuid
        WHERE s.game_start_ts >= ?
          AND s.queue_id IN ({placeholders})
          AND s.position != 'UTILITY'
          AND m.duration_s IS NOT NULL
          AND m.duration_s >= ?
        GROUP BY p.riot_id
        """,
        params,
    ).fetchall()

    return {
        r["riot_id"]: (int(r["games"] or 0), float(r["avg_cs_min"] or 0.0))
        for r in rows
    }




def compute_worst_stat_line(conn, start_ts, enabled_queues, min_duration_s=600):
    if not enabled_queues:
        return None

    placeholders = ",".join("?" for _ in enabled_queues)
    params = [start_ts, *enabled_queues, min_duration_s]

    row = conn.execute(
        f"""
        SELECT
          p.riot_id,
          s.champion_name,
          s.kills,
          s.deaths,
          s.assists,
          s.win,
          s.queue_id,
          m.duration_s
        FROM player_match_stats s
        JOIN players p ON p.puuid = s.puuid
        JOIN matches m ON m.match_id = s.match_id
        WHERE s.game_start_ts >= ?
          AND s.queue_id IN ({placeholders})
          AND m.duration_s >= ?
          AND s.deaths > 0
        ORDER BY
          ((s.kills + s.assists) * 1.0 / s.deaths) ASC,
          s.deaths DESC,
          m.duration_s DESC
        LIMIT 1
        """,
        params,
    ).fetchone()

    return row

def is_support_this_week(conn, puuid, start_ts, threshold=0.6):
    """
    Returns True if at least `threshold` of the player's games
    in the time window were played as support (UTILITY).
    """
    rows = conn.execute(
        """
        SELECT position, COUNT(*) AS n
        FROM player_match_stats
        WHERE puuid = ? AND game_start_ts >= ?
        GROUP BY position
        """,
        (puuid, start_ts),
    ).fetchall()

    total_games = sum(r["n"] for r in rows)
    if total_games == 0:
        return False

    support_games = sum(r["n"] for r in rows if r["position"] == "UTILITY")
    support_ratio = support_games / total_games

    return support_ratio >= threshold


def main_role_this_week(conn, puuid, start_ts):
    """
    Returns the most-played role (TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY)
    in the time window.
    """
    row = conn.execute(
        """
        SELECT position, COUNT(*) AS n
        FROM player_match_stats
        WHERE puuid = ? AND game_start_ts >= ?
        GROUP BY position
        ORDER BY n DESC
        LIMIT 1
        """,
        (puuid, start_ts),
    ).fetchone()

    if not row or not row["position"]:
        return "UNKNOWN"
    return row["position"]



def compute_weekly_queue_games(conn, start_ts, queue_ids):
    """
    Count games per player for multiple queue IDs in the time window.
    queue_ids: list/set of ints (e.g. [1700] or [450, 1700])
    Returns dict: riot_id -> games
    """
    queue_ids = list(queue_ids)
    if not queue_ids:
        return {}

    placeholders = ",".join("?" for _ in queue_ids)
    params = [start_ts, *queue_ids]

    rows = conn.execute(
        f"""
        SELECT p.riot_id AS riot_id, COUNT(*) AS games
        FROM player_match_stats s
        JOIN players p ON p.puuid = s.puuid
        WHERE s.game_start_ts >= ?
          AND s.queue_id IN ({placeholders})
        GROUP BY p.riot_id
        """,
        params,
    ).fetchall()

    return {r["riot_id"]: int(r["games"]) for r in rows}





def compute_weekly_time_dead(conn, start_ts, queue_ids):
    """
    Returns dict: riot_id -> (games_with_data, total_dead_s, avg_dead_s)
    Only counts games where time_dead_s is not NULL.
    """
    queue_ids = list(queue_ids)
    if not queue_ids:
        return {}

    placeholders = ",".join("?" for _ in queue_ids)
    params = [start_ts, *queue_ids]

    rows = conn.execute(
        f"""
        SELECT
          p.riot_id AS riot_id,
          COUNT(s.time_dead_s) AS games_with_data,
          SUM(COALESCE(s.time_dead_s, 0)) AS total_dead_s,
          AVG(COALESCE(s.time_dead_s, 0)) AS avg_dead_s
        FROM player_match_stats s
        JOIN players p ON p.puuid = s.puuid
        WHERE s.game_start_ts >= ?
          AND s.queue_id IN ({placeholders})
          AND s.time_dead_s IS NOT NULL
        GROUP BY p.riot_id
        """,
        params,
    ).fetchall()

    return {
        r["riot_id"]: (
            int(r["games_with_data"] or 0),
            int(r["total_dead_s"] or 0),
            float(r["avg_dead_s"] or 0.0),
        )
        for r in rows
    }























def main():
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("WEBHOOK_URL not set")

    cfg = load_config("config.yaml")
    lookback_days = int(cfg.get("app", {}).get("lookback_days", 7))
    now = int(time.time())
    start_ts = now - lookback_days * 24 * 60 * 60

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Players we have in DB (should have been created by ingest step)
    players = conn.execute("SELECT puuid, riot_id FROM players ORDER BY riot_id").fetchall()
    if not players:
        conn.close()
        raise RuntimeError("No players in DB. Run ingest.py first.")

    # Queues that count for normal stats (exclude ARAM / Mayhem)
    stat_queue_ids = queue_ids_excluding_labels(cfg, excluded_prefixes=["aram"])
    
    fun_queue_ids = queue_ids_including_labels(cfg, included_prefixes=["aram"])

    # Precompute CS/min per player for the week (used for CS awards)
    csmin_by_riot_id = compute_weekly_cs_per_min(conn, start_ts, stat_queue_ids)
    aram_like_games = compute_weekly_queue_games(conn, start_ts, fun_queue_ids)
    time_dead_by_riot_id = compute_weekly_time_dead(conn, start_ts, stat_queue_ids)
    summaries = []     # (riot_id, summary_text)
    leaderboard = []   # (riot_id, games, winrate, kda)
    positions = {}     # riot_id -> primary_position

    # -------- KDA AWARDS tracking --------
    MIN_GAMES_FOR_AWARDS = 2
    candidates_for_awards = []  # (riot_id, games, kda, total_k, total_d, total_a)

    for row in players:
        puuid = row["puuid"]
        riot_id = row["riot_id"]

        # Determine primary position this week (used later for CS/min fairness)
        is_support = is_support_this_week(conn, puuid, start_ts)
        positions[riot_id] = is_support
        main_role = main_role_this_week(conn, puuid, start_ts)


        enabled = stat_queue_ids
        if not enabled:
            summaries.append((riot_id, 0, "No enabled queues."))
            leaderboard.append((riot_id, 0, 0.0, 0.0))
            continue

        placeholders = ",".join("?" for _ in enabled)
        params = [puuid, start_ts, *enabled]

        agg = conn.execute(
            f"""
            SELECT
              COUNT(*) AS games,
              SUM(win) AS wins,
              SUM(kills) AS k,
              SUM(deaths) AS d,
              SUM(assists) AS a,
              AVG(kills) AS avg_k,
              AVG(deaths) AS avg_d,
              AVG(assists) AS avg_a
            FROM player_match_stats
            WHERE puuid = ?
              AND game_start_ts >= ?
              AND queue_id IN ({placeholders})
            """,
            params,
        ).fetchone()

        games = int(agg["games"] or 0)
        if games == 0:
            summaries.append((riot_id, 0, f"0 games in last {lookback_days} days"))
            leaderboard.append((riot_id, 0, 0.0, 0.0))
            continue

        wins = int(agg["wins"] or 0)
        winrate = (wins / games) * 100.0

        total_k = int(agg["k"] or 0)
        total_d = int(agg["d"] or 0)
        total_a = int(agg["a"] or 0)

        avg_k = float(agg["avg_k"] or 0.0)
        avg_d = float(agg["avg_d"] or 0.0)
        avg_a = float(agg["avg_a"] or 0.0)

        kda = kda_ratio(total_k, total_d, total_a)

        if games >= MIN_GAMES_FOR_AWARDS:
            candidates_for_awards.append((riot_id, games, kda, total_k, total_d, total_a))

        # Top champs
        champs = conn.execute(
            f"""
            SELECT champion_name, COUNT(*) AS games, SUM(win) AS wins
            FROM player_match_stats
            WHERE puuid = ?
              AND game_start_ts >= ?
              AND queue_id IN ({placeholders})
            GROUP BY champion_name
            ORDER BY games DESC, wins DESC
            LIMIT 3
            """,
            params,
        ).fetchall()

        champ_lines = []
        for c in champs:
            c_games = int(c["games"])
            c_wins = int(c["wins"] or 0)
            c_wr = (c_wins / c_games) * 100.0 if c_games else 0.0
            champ_lines.append(f"{c['champion_name']}: {c_games}g ({c_wr:.0f}% WR)")

        # CS/min display (optional in per-player block)
        cs_games, csmin = csmin_by_riot_id.get(riot_id, (0, 0.0))
        csmin_line = f"CS/min: **{csmin:.2f}**" if cs_games > 0 else "CS/min: —"


        dead_games, total_dead_s, avg_dead_s = time_dead_by_riot_id.get(riot_id, (0, 0, 0.0))
        if dead_games > 0:
            dead_block = (
                f"Average Time Spent Dead: **{(avg_dead_s/60):.1f} min/game**\n"
                f"Total Time Spent Dead: **{(total_dead_s/60):.1f} min** over **{dead_games} games**"
            )
        else:
            dead_block = "Average Time Spent Dead: —\nTotal Time Spent Dead: —"

        block = (
            f"Most Played Role: **{main_role}**\n"
            f"**{games} games** • **{wins}W** • **{winrate:.1f}% WR**\n"
            f"Avg: **{avg_k:.1f}/{avg_d:.1f}/{avg_a:.1f}** • KDA **{kda:.2f}**\n"
            f"{csmin_line}\n"
            f"Top champs: " + (", ".join(champ_lines) if champ_lines else "—") + "\n"
            f"{dead_block}"
        )


        summaries.append((riot_id, games, block))
        leaderboard.append((riot_id, games, winrate, kda))

    # -------- KDA awards --------
    potw_text = "Not enough data (need at least 3 games)."
    lotw_text = "Not enough data (need at least 3 games)."

    if candidates_for_awards:
        best = max(candidates_for_awards, key=lambda x: (x[2], x[1]))   # kda then games
        worst = min(candidates_for_awards, key=lambda x: (x[2], -x[1])) # kda then games (avoid tiny sample “winning” worst)

        best_id, best_games, best_kda, bk, bd, ba = best
        worst_id, worst_games, worst_kda, wk, wd, wa = worst
        potw_mention = discord_mention_for_riot_id(cfg, best_id)
        lotw_mention = discord_mention_for_riot_id(cfg, worst_id)
        potw_text = f"**{potw_mention}** — KDA **{best_kda:.2f}** over **{best_games}** games ({bk}/{bd}/{ba})"
        lotw_text = f"**{lotw_mention}** — KDA **{worst_kda:.2f}** over **{worst_games}** games ({wk}/{wd}/{wa})"

    # -------- CS/min awards (non-support only) --------
    cs_winner_text = "Not enough data (need at least 3 games, non-support)."
    cs_loser_text  = "Not enough data (need at least 3 games, non-support)."
    MIN_GAMES_FOR_CSM = 2

    cs_candidates = []
    for row in players:
        riot_id = row["riot_id"]
        # exclude supports
        if positions.get(riot_id):
            continue

        games, csmin = csmin_by_riot_id.get(riot_id, (0, 0.0))
        if games >= MIN_GAMES_FOR_CSM:
            cs_candidates.append((riot_id, games, csmin))

    summaries.sort(key=lambda x: x[1], reverse=True)

    if cs_candidates:
        # pick winners
        cs_best = max(cs_candidates, key=lambda x: x[2])   # highest CS/min
        cs_worst = min(cs_candidates, key=lambda x: x[2])  # lowest CS/min

        # unpack tuples
        cs_best_id, cs_best_games, cs_best_csmin = cs_best
        cs_worst_id, cs_worst_games, cs_worst_csmin = cs_worst

        cs_winping = discord_mention_for_riot_id(cfg, cs_best_id)
        cs_loseping = discord_mention_for_riot_id(cfg, cs_worst_id)
        cs_winner_text = (
            f"**{cs_winping}** — **{cs_best_csmin:.2f} CS/min** "
            f"over **{cs_best_games}** games"
        )
        cs_loser_text = (
            f"**{cs_loseping}** — **{cs_worst_csmin:.2f} CS/min** "
            f"over **{cs_worst_games}** games"
        )







    # --- NEW: Mayhem Warrior award ---
    mayhem_warrior_text = "No ARAM Mayhem games played this week."

    if aram_like_games:
        winner_id, winner_games = max(aram_like_games.items(), key=lambda x: x[1])
        if winner_games > 0:
            mayhem_mention = discord_mention_for_riot_id(cfg, winner_id)
            mayhem_warrior_text = f"{mayhem_mention} — **{winner_games} Mayhem games** played"
        
    
    #worst game award
    worst_game = compute_worst_stat_line(conn, start_ts, stat_queue_ids)

    if worst_game:
        rid = worst_game["riot_id"]
        mention = discord_mention_for_riot_id(cfg, rid)

        k = int(worst_game["kills"] or 0)
        d = int(worst_game["deaths"] or 0)
        a = int(worst_game["assists"] or 0)
        kda = (k + a) / d if d else 0.0

        wl = "Win" if worst_game["win"] else "Loss"
        mins = int(worst_game["duration_s"] or 0) // 60

        worst_stat_line_text = (
            f"{mention} — **{worst_game['champion_name']}**\n"
            f"**{k}/{d}/{a}** • KDA **{kda:.2f}** • {wl} • **{mins}m**"
        )
    else:
        worst_stat_line_text = "No eligible games this week."





        # -------- Average Time Dead per Game award --------
    avg_dead_award_text = "Not enough data yet."

    MIN_GAMES_FOR_AVG_DEAD = 1
    avg_dead_candidates = []

    for riot_id, (g, total_dead_s, avg_dead_s) in time_dead_by_riot_id.items():
        if g >= MIN_GAMES_FOR_AVG_DEAD:
            avg_dead_candidates.append((riot_id, g, total_dead_s, avg_dead_s))

    if avg_dead_candidates:
        # Highest average time dead per game
        worst_avg = max(avg_dead_candidates, key=lambda x: x[3])
        rid, g, total_dead_s, avg_dead_s = worst_avg
        mention = discord_mention_for_riot_id(cfg, rid)

        avg_dead_award_text = (
            f"{mention} — avg **{(avg_dead_s/60):.1f} min/game** "
            f"(total **{(total_dead_s/60):.1f} min** over **{g} games**)"
        )
































    # -------- Leaderboard --------
    min_games = 3
    leaderboard_sorted = sorted(
        leaderboard,
        key=lambda x: (
            0 if x[1] >= min_games else 1,
            -(x[2] if x[1] >= min_games else -1),
            -x[1],
            -x[3],
        ),
    )

    top_lines = []
    for i, (rid, games, wr, kda) in enumerate(leaderboard_sorted[:11], start=1):
        if games == 0:
            top_lines.append(f"{i}. {rid} — 0 games")
        else:
            top_lines.append(f"{i}. {rid} — {games} games, {wr:.1f}% WR, KDA {kda:.2f}")

    # -------- Build embeds --------
    divider = "```─────────────────── ❖ ───────────────────```"



    time_of_the_week = {
        "title": "YOU KNOW WHAT TIME IT IS",
        "description": "I the chud son poro :fire: :fire: will be hosting the stats of this week!",
        "image": {
            "url": "https://pbs.twimg.com/media/G2rhQpUWQAA0Wy3.jpg"
        }

    }
    awards_embed = {
        "title": "🏆 Hall of Fame",
        "description": f"Last {lookback_days} days",
        "color": 0xFFD700,
        "fields": [
            {"name": "👑 Player of the Week (Highest KDA)", "value": potw_text, "inline": False},
            {"name": "🌾 CS/min Winner (Non-support)", "value": cs_winner_text, "inline": False},
            {"name": "❄️ ARAM Warrior", "value": mayhem_warrior_text, "inline": False},
            

        ],
    }

    clown_embed = {
        "title": ":clown: Hall of Shame",
        "description": f"Last {lookback_days} days",
        "color": 0xdb1620,
        "fields": [
            {"name": "💀 Most Boosted of the Week (Lowest KDA)", "value": lotw_text, "inline": False},
            {"name": "🥀 CS/min Loser (Non-support)", "value": cs_loser_text, "inline": False},
            {"name": "🧠 Highest Avg Time Dead / Game", "value": avg_dead_award_text, "inline": False},
            {"name": "🧻 Worst Stat Line of the Week", "value": worst_stat_line_text, "inline": False,}
        ]
    }

    leaderboard_embed = {
        "title": "📊 Leaderboard",
        "color": 0x3498DB,
        "fields": [
            {
                "name": "Top Players",
                "value": "\n".join(top_lines) if top_lines else "—",
                "inline": False,
            }
        ],
    }

    # Player stats embeds (chunked)
    player_embeds = []
    current_chunk = ""
    chunk_index = 1

    for riot_id, games, text in summaries:
        entry = f"**{riot_id}**\n{text}\n\n"
        if len(current_chunk) + len(entry) > 3500:
            player_embeds.append({
                "title": f"👥 Player Stats (part {chunk_index})",
                "description": current_chunk.strip(),
                "color": 0x95A5A6,
            })
            chunk_index += 1
            current_chunk = entry
        else:
            current_chunk += entry

    if current_chunk.strip():
        player_embeds.append({
            "title": f"👥 Player Stats (part {chunk_index})",
            "description": current_chunk.strip(),
            "color": 0x95A5A6,
        })

    # Send (max 10 embeds per message)
    embeds = [time_of_the_week, awards_embed, clown_embed, leaderboard_embed] + player_embeds
    for i in range(0, len(embeds), 10):
        post_embeds(webhook_url, embeds[i:i+10])

    conn.close()
    print("✅ Weekly report posted (with KDA + CS/min awards).")

if __name__ == "__main__":
    main()
