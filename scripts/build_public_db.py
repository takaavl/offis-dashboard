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
    with connect() as con:
        maps=con.execute('SELECT id,raw_json,team_id FROM maps').fetchall()
        for m in maps:
            canonical={r['account_riot_id']:r['canonical_name'] for r in con.execute('''SELECT pms.account_riot_id,p.canonical_name FROM player_map_stats pms JOIN players p ON p.id=pms.player_id WHERE pms.map_id=?''',(m['id'],)).fetchall()}
            upsert_map_caches(con,m['id'],m['raw_json'],m['team_id'],canonical)
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
