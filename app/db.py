import sqlite3
from contextlib import contextmanager
from .config import DB_PATH

SCHEMA = r'''
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL UNIQUE,
    roster_status TEXT NOT NULL CHECK(roster_status IN ('main','recurring_sub','former_sub','wel_sub','occasional_sub')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS player_aliases (
    id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    riot_id TEXT NOT NULL UNIQUE,
    alias_type TEXT NOT NULL DEFAULT 'own_account',
    note TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    competition TEXT NOT NULL,
    event_notes TEXT,
    placement_text TEXT,
    first_date TEXT,
    last_date TEXT
);

CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    series_key TEXT NOT NULL UNIQUE,
    stage TEXT,
    opponent TEXT NOT NULL,
    played_at TEXT,
    best_of INTEGER NOT NULL DEFAULT 1,
    maps_won INTEGER NOT NULL DEFAULT 0,
    maps_lost INTEGER NOT NULL DEFAULT 0,
    result TEXT CHECK(result IN ('W','L','D','N/A')),
    roster_category TEXT,
    is_bye INTEGER NOT NULL DEFAULT 0,
    bye_result TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS maps (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    match_id TEXT UNIQUE,
    map_index INTEGER NOT NULL DEFAULT 1,
    map_name TEXT NOT NULL,
    map_image_url TEXT,
    played_at TEXT,
    duration_ms INTEGER,
    raw_rounds INTEGER,
    official_rounds INTEGER,
    team_id TEXT,
    start_side TEXT,
    score_for INTEGER NOT NULL,
    score_against INTEGER NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('W','L','D')),
    roster_category TEXT NOT NULL,
    composition_key TEXT,
    data_quality TEXT NOT NULL DEFAULT 'complete' CHECK(data_quality IN ('complete','partial','manual_result')),
    stats_complete INTEGER NOT NULL DEFAULT 1,
    source_path TEXT NOT NULL UNIQUE,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS map_pistols (
    map_id INTEGER PRIMARY KEY REFERENCES maps(id) ON DELETE CASCADE,
    pistol_wins INTEGER NOT NULL DEFAULT 0,
    pistol_played INTEGER NOT NULL DEFAULT 0,
    attack_wins INTEGER NOT NULL DEFAULT 0,
    attack_played INTEGER NOT NULL DEFAULT 0,
    defense_wins INTEGER NOT NULL DEFAULT 0,
    defense_played INTEGER NOT NULL DEFAULT 0,
    conversion_wins INTEGER NOT NULL DEFAULT 0,
    conversion_opportunities INTEGER NOT NULL DEFAULT 0,
    first_half_result TEXT,
    second_half_result TEXT
);

CREATE TABLE IF NOT EXISTS player_map_stats (
    id INTEGER PRIMARY KEY,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    account_riot_id TEXT NOT NULL,
    agent TEXT,
    agent_image_url TEXT,
    agent_portrait_url TEXT,
    rank TEXT,
    rank_tier_id INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    kd REAL,
    acs REAL,
    adr REAL,
    kast REAL,
    first_kills INTEGER,
    first_deaths INTEGER,
    damage_delta_per_round REAL,
    headshot_pct REAL,
    plants INTEGER,
    defuses INTEGER,
    UNIQUE(map_id, player_id)
);

CREATE TABLE IF NOT EXISTS substitutions (
    id INTEGER PRIMARY KEY,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    sub_player_id INTEGER NOT NULL REFERENCES players(id),
    replaced_player_id INTEGER REFERENCES players(id),
    confidence TEXT NOT NULL CHECK(confidence IN ('exact','ambiguous')),
    note TEXT
);

CREATE TABLE IF NOT EXISTS map_team_insights_cache (
    map_id INTEGER PRIMARY KEY REFERENCES maps(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS map_leaderboard_cache (
    map_id INTEGER PRIMARY KEY REFERENCES maps(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_issues (
    id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','error')),
    issue_type TEXT NOT NULL,
    source_path TEXT,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_maps_played_at ON maps(played_at);
CREATE INDEX IF NOT EXISTS idx_maps_roster_category ON maps(roster_category);
CREATE INDEX IF NOT EXISTS idx_series_played_at ON series(played_at);
CREATE INDEX IF NOT EXISTS idx_series_roster_category ON series(roster_category);
CREATE INDEX IF NOT EXISTS idx_pms_player ON player_map_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_pms_map ON player_map_stats(map_id);
'''

@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db(reset=False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
