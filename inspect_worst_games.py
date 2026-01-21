from dotenv import load_dotenv
load_dotenv()

import sqlite3
import requests
import os
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "stats.db")
print("Using DB_PATH:", DB_PATH)
if not Path(DB_PATH).exists():
    raise FileNotFoundError(f"{DB_PATH} not found")


def post_embeds(webhook_url, embeds):
    # Same shape as weekly_report.py
    r = requests.post(webhook_url, json={"embeds": embeds}, timeout=15)
    r.raise_for_status()

def worst_game_for_player(conn, puuid):
    return conn.execute(
        """
        SELECT
          s.match_id,
          s.champion_name,
          s.kills,
          s.deaths,
          s.assists,
          s.win,
          s.queue_id,
          s.game_start_ts,
          CASE
            WHEN s.deaths = 0 THEN (s.kills + s.assists) * 1.0
            ELSE (s.kills + s.assists) * 1.0 / s.deaths
          END AS kda
        FROM player_match_stats s
        WHERE s.puuid = ?
            AND NOT (s.kills = 0 AND s.deaths = 0 AND s.assists = 0)
        ORDER BY
          kda ASC,
          s.deaths DESC,
          (s.kills + s.assists) ASC
        LIMIT 1
        """,
        (puuid,),
    ).fetchone()

def main():
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("WEBHOOK_URL not set in environment (.env)")

    if not Path(DB_PATH).exists():
        raise FileNotFoundError("stats.db not found (run ingest.py first)")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    players = conn.execute(
        "SELECT puuid, riot_id FROM players ORDER BY riot_id"
    ).fetchall()

    if not players:
        conn.close()
        raise RuntimeError("No players in DB. Run ingest.py first.")

    # Build big text block, then chunk into multiple embeds (Discord limits)
    lines = []
    for p in players:
        puuid = p["puuid"]
        riot_id = p["riot_id"]

        row = worst_game_for_player(conn, puuid)
        if not row:
            lines.append(f"**{riot_id}**\nNo games recorded.\n")
            continue

        champ = row["champion_name"] or "Unknown"
        k, d, a = int(row["kills"]), int(row["deaths"]), int(row["assists"])
        kda = float(row["kda"]) if row["kda"] is not None else 0.0
        result = "Win" if row["win"] else "Loss"

        lines.append(
            f"**{riot_id}**\n"
            f"{champ} — **{k}/{d}/{a}** (KDA **{kda:.2f}**) — {result}\n"
            f"`match={row['match_id']} queue={row['queue_id']} ts={row['game_start_ts']}`\n"
        )

    conn.close()

    header = "All-time worst stored game per player (lowest KDA)."
    divider = "```─────────────────── ❖ ───────────────────```"

    embeds = []
    chunk = ""
    part = 1

    # keep a safe margin under Discord embed description limit (4096)
    MAX_DESC = 3500

    for entry in lines:
        entry = entry + "\n"
        if len(chunk) + len(entry) > MAX_DESC:
            embeds.append({
                "title": f"💀 Hall of Shame (All Time) — part {part}",
                "description": f"{header}\n{divider}\n{chunk}".strip(),
                "color": 0xE74C3C,
            })
            part += 1
            chunk = entry
        else:
            chunk += entry

    if chunk.strip():
        embeds.append({
            "title": f"💀 Hall of Shame (All Time) — part {part}",
            "description": f"{header}\n{divider}\n{chunk}".strip(),
            "color": 0xE74C3C,
        })

    # Discord allows max 10 embeds per message, so send in batches
    for i in range(0, len(embeds), 10):
        post_embeds(webhook_url, embeds[i:i+10])

    print(f"✅ Posted {len(players)} players' worst games across {len(embeds)} embed(s).")

if __name__ == "__main__":
    main()
