from __future__ import annotations
import json, shutil, sqlite3, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.db import init_db, connect
from app.analytics import upsert_map_caches

DB=ROOT/'data'/'team_dashboard.sqlite3'
FULL=ROOT/'data'/'private_full.sqlite3'


def main():
    init_db(reset=False)
    full_con = None
    if FULL.exists():
        full_con = sqlite3.connect(FULL)
        full_con.row_factory = sqlite3.Row
    try:
        with connect() as con:
            maps=con.execute('SELECT id,raw_json,team_id FROM maps').fetchall()
            for m in maps:
                raw_json = m['raw_json'] or ''
                if not raw_json:
                    # The public DB deliberately strips raw Tracker JSON after the
                    # first deploy preparation. Preserve valid historical caches.
                    cache_count = con.execute(
                        'SELECT (SELECT COUNT(*) FROM map_team_insights_cache WHERE map_id=?) + '
                        '(SELECT COUNT(*) FROM map_leaderboard_cache WHERE map_id=?)',
                        (m['id'], m['id'])
                    ).fetchone()[0]
                    leaderboard_row = con.execute(
                        'SELECT payload_json FROM map_leaderboard_cache WHERE map_id=?', (m['id'],)
                    ).fetchone()
                    player_count = con.execute(
                        'SELECT COUNT(*) FROM player_map_stats WHERE map_id=?', (m['id'],)
                    ).fetchone()[0]
                    try:
                        leaderboard_payload = json.loads(leaderboard_row['payload_json']) if leaderboard_row else None
                    except Exception:
                        leaderboard_payload = None
                    # Empty leaderboards alongside stored player stats indicate the
                    # previous buggy prepare run may already have overwritten cache
                    # content. In that case, recover from the private full archive.
                    cache_is_valid = cache_count == 2 and (
                        bool(leaderboard_payload) or player_count == 0
                    )
                    if cache_is_valid:
                        continue
                    if full_con is not None:
                        full_row = full_con.execute('SELECT raw_json FROM maps WHERE id=?', (m['id'],)).fetchone()
                        if full_row and full_row['raw_json']:
                            raw_json = full_row['raw_json']
                    if not raw_json:
                        # Preserve any existing cache rather than replacing it
                        # with empty data when no raw source is available.
                        continue
                canonical={r['account_riot_id']:r['canonical_name'] for r in con.execute('''SELECT pms.account_riot_id,p.canonical_name FROM player_map_stats pms JOIN players p ON p.id=pms.player_id WHERE pms.map_id=?''',(m['id'],)).fetchall()}
                upsert_map_caches(con,m['id'],raw_json,m['team_id'],canonical)
    finally:
        if full_con is not None:
            full_con.close()
    # Keep the original historical full/raw archive once it exists.
    # Future admin imports are archived individually in data/private_raw/.
    if not FULL.exists():
        shutil.copy2(DB,FULL)
    with sqlite3.connect(DB) as con:
        con.execute("UPDATE maps SET raw_json='' WHERE raw_json<>''")
        con.commit()
        con.execute('VACUUM')
    print(json.dumps({'public_db_mb':round(DB.stat().st_size/1024/1024,2),'private_full_db_mb':round(FULL.stat().st_size/1024/1024,2)},indent=2))

if __name__=='__main__': main()
