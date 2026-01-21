PRAGMA foreign_keys = ON;

-- 1) Players you track (stable identity = puuid)
CREATE TABLE IF NOT EXISTS players (
  puuid            TEXT PRIMARY KEY,
  riot_id          TEXT NOT NULL,          -- "Name#TAG"
  platform         TEXT NOT NULL,          -- e.g. EUW1
  routing          TEXT NOT NULL,          -- e.g. EUROPE
  added_at         INTEGER NOT NULL DEFAULT (unixepoch()),
  last_seen_at     INTEGER                -- last time we ingested for this player
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_players_riot_id ON players(riot_id);

-- 2) Matches (one row per matchId, shared across all players)
CREATE TABLE IF NOT EXISTS matches (
  match_id         TEXT PRIMARY KEY,       -- e.g. "EUW1_1234567890"
  routing          TEXT NOT NULL,           -- EUROPE/AMERICAS/ASIA/SEA (helps sanity)
  platform         TEXT,                   -- optional (derived from matchId prefix usually)
  queue_id         INTEGER,                -- 420/440/400 etc.
  game_start_ts    INTEGER,                -- seconds since epoch
  duration_s       INTEGER,                -- gameDuration in seconds
  game_mode        TEXT,                   -- e.g. CLASSIC
  game_type        TEXT,                   -- e.g. MATCHED_GAME
  map_id           INTEGER,
  patch           TEXT,                    -- optional: store if you compute it
  ingested_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_matches_start_ts ON matches(game_start_ts);
CREATE INDEX IF NOT EXISTS idx_matches_queue_ts ON matches(queue_id, game_start_ts);

-- 3) Per-player-per-match stats (this is your main fact table)
CREATE TABLE IF NOT EXISTS player_match_stats (
  puuid                 TEXT NOT NULL,
  match_id              TEXT NOT NULL,
  time_dead_s           INTEGER,

  -- outcome/context
  win                   INTEGER NOT NULL,      -- 0/1
  team_id               INTEGER,               -- 100/200
  role                  TEXT,                  -- e.g. TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY (optional)
  lane                  TEXT,                  -- Riot lane field (optional)
  position              TEXT,                  -- Riot teamPosition (optional)

  -- champion + basic combat
  champion_id           INTEGER,
  champion_name         TEXT,                  -- handy for reports; optional if you map IDs later
  kills                 INTEGER NOT NULL,
  deaths                INTEGER NOT NULL,
  assists               INTEGER NOT NULL,

  -- farming + economy
  cs                    INTEGER,               -- totalMinionsKilled + neutralMinionsKilled
  gold_earned           INTEGER,
  gold_spent            INTEGER,

  -- damage
  dmg_to_champs         INTEGER,
  dmg_taken             INTEGER,

  -- vision/objectives (optional but useful)
  vision_score          INTEGER,
  wards_placed          INTEGER,
  wards_killed          INTEGER,
  turret_kills          INTEGER,

  -- timestamps for convenience (copied from matches to speed certain queries)
  game_start_ts         INTEGER NOT NULL,
  queue_id              INTEGER,

  PRIMARY KEY (puuid, match_id),
  FOREIGN KEY (puuid) REFERENCES players(puuid) ON DELETE CASCADE,
  FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pms_puuid_ts ON player_match_stats(puuid, game_start_ts);
CREATE INDEX IF NOT EXISTS idx_pms_ts ON player_match_stats(game_start_ts);
CREATE INDEX IF NOT EXISTS idx_pms_queue_ts ON player_match_stats(queue_id, game_start_ts);

-- 4) Ingest checkpoint (so you only fetch "new stuff")
-- If you prefer, you can store this in players.last_seen_at instead.
CREATE TABLE IF NOT EXISTS ingest_state (
  puuid             TEXT PRIMARY KEY,
  last_end_time_ts  INTEGER NOT NULL,  -- last time window end you successfully ingested to
  updated_at        INTEGER NOT NULL DEFAULT (unixepoch()),
  FOREIGN KEY (puuid) REFERENCES players(puuid) ON DELETE CASCADE
);

-- 5) Optional: store queue definitions (handy for labeling)
CREATE TABLE IF NOT EXISTS queues (
  queue_id      INTEGER PRIMARY KEY,   -- 420 etc.
  label         TEXT NOT NULL           -- "Ranked Solo"
);

-- 6) Table for High Scores
CREATE TABLE IF NOT EXISTS records (
  key        TEXT PRIMARY KEY,
  value      REAL NOT NULL,
  meta_json  TEXT,
  updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
