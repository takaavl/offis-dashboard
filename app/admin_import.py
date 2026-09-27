from __future__ import annotations

import json, re, unicodedata
from pathlib import Path
from datetime import datetime, timezone

from .config import ROOT
from .analytics import getv, upsert_map_caches

MAIN_PLAYERS = ["Lugia", "Lindorm", "LJPH", "CeCe", "Duke"]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "item"


def ensure_player(con, name: str, status: str = "occasional_sub", active: int = 0):
    slug = slugify(name)
    con.execute("INSERT OR IGNORE INTO players(slug,canonical_name,roster_status,active) VALUES(?,?,?,?)", (slug,name,status,active))
    return con.execute("SELECT id FROM players WHERE canonical_name=?", (name,)).fetchone()[0]


def round_side(segments, round_no, team_id):
    for s in segments:
        if s.get("type") == "player-round" and s.get("attributes",{}).get("round") == round_no and s.get("metadata",{}).get("teamId") == team_id:
            return s.get("metadata",{}).get("teamSide")
    return None


def round_winner(round_summaries, round_no):
    s = next((x for x in round_summaries if x.get("attributes",{}).get("round") == round_no), None)
    return getv(s.get("stats",{}), "winningTeam") if s else None


def pistol_metrics(segments, team_id):
    rounds = [s for s in segments if s.get("type") == "round-summary"]
    out=dict(pistol_wins=0,pistol_played=0,attack_wins=0,attack_played=0,defense_wins=0,defense_played=0,conversion_wins=0,conversion_opportunities=0,first_half_result=None,second_half_result=None)
    for label,pistol_round,next_round in (("first_half_result",1,2),("second_half_result",13,14)):
        winner=round_winner(rounds,pistol_round)
        if winner is None: continue
        side=round_side(segments,pistol_round,team_id)
        won=winner==team_id
        out["pistol_played"]+=1; out["pistol_wins"]+=int(won); out[label]="W" if won else "L"
        if side=="attacker": out["attack_played"]+=1; out["attack_wins"]+=int(won)
        elif side=="defender": out["defense_played"]+=1; out["defense_wins"]+=int(won)
        if won:
            nxt=round_winner(rounds,next_round)
            if nxt is not None:
                out["conversion_opportunities"]+=1; out["conversion_wins"]+=int(nxt==team_id)
    return out


def parse_overrides(text: str):
    out={}
    for line in (text or "").splitlines():
        line=line.strip()
        if not line: continue
        if "=" not in line:
            raise ValueError(f"Override invalide: {line!r}. Utilise RiotID#TAG=Nom")
        riot,name=line.split("=",1)
        out[riot.strip()]=name.strip()
    return out


def _alias_map(con):
    return {r["riot_id"]: r["canonical_name"] for r in con.execute("SELECT pa.riot_id,p.canonical_name FROM player_aliases pa JOIN players p ON p.id=pa.player_id")}


def _pick_team_id(psummary, alias_map, overrides, explicit_team_id=None):
    if explicit_team_id in ("Red","Blue"):
        return explicit_team_id
    counts={}
    for p in psummary:
        account=p.get("attributes",{}).get("platformUserIdentifier")
        if account in overrides or account in alias_map:
            tid=p.get("metadata",{}).get("teamId")
            counts[tid]=counts.get(tid,0)+1
    if not counts:
        raise ValueError("Impossible d'identifier notre équipe. Choisis Red/Blue manuellement ou ajoute un override de compte.")
    team_id,n=max(counts.items(), key=lambda kv:kv[1])
    if n < 3:
        raise ValueError("Identification de l'équipe trop incertaine (<3 comptes connus). Choisis Red/Blue manuellement.")
    return team_id


def import_official_map(con, raw_text: str, *, existing_series_id: int|None, event_name: str, competition: str, stage: str,
                        opponent: str, best_of: int, series_code: str, map_index: int|None, explicit_team_id: str|None,
                        overrides_text: str = ""):
    obj=json.loads(raw_text)
    data=obj.get("data",{}); attrs=data.get("attributes",{}); md=data.get("metadata",{}); segments=data.get("segments",[])
    match_id=attrs.get("id")
    if not match_id: raise ValueError("match_id introuvable dans le JSON Tracker")
    if con.execute("SELECT 1 FROM maps WHERE match_id=?", (match_id,)).fetchone():
        raise ValueError("Cette game existe déjà dans la base (match_id dupliqué).")
    psummary=[s for s in segments if s.get("type")=="player-summary"]
    if not psummary: raise ValueError("Aucun player-summary trouvé dans le JSON")

    overrides=parse_overrides(overrides_text)
    alias_map=_alias_map(con)
    team_id=_pick_team_id(psummary, alias_map, overrides, explicit_team_id)

    actual_by_account={}
    roster=[]
    for p in psummary:
        if p.get("metadata",{}).get("teamId") != team_id: continue
        account=p.get("attributes",{}).get("platformUserIdentifier")
        canonical=overrides.get(account) or alias_map.get(account)
        if not canonical:
            canonical=(account or "Unknown").split("#",1)[0].strip() or "Unknown"
            pid=ensure_player(con, canonical)
            con.execute("INSERT OR IGNORE INTO player_aliases(player_id,riot_id,alias_type,note) VALUES(?,?,?,?)", (pid,account,"admin_discovered","Added from admin import"))
            alias_map[account]=canonical
        else:
            pid=ensure_player(con, canonical)
            if account and account not in alias_map:
                con.execute("INSERT OR IGNORE INTO player_aliases(player_id,riot_id,alias_type,note) VALUES(?,?,?,?)", (pid,account,"admin_override","Mapped from admin import"))
                alias_map[account]=canonical
        actual_by_account[account]=canonical; roster.append(canonical)

    status_by_name={r["canonical_name"]:r["roster_status"] for r in con.execute("SELECT canonical_name,roster_status FROM players")}
    main_missing=[p for p in MAIN_PLAYERS if p not in roster]
    subs=[p for p in roster if p not in MAIN_PLAYERS]
    if not subs and not main_missing: roster_category="core"
    elif any(status_by_name.get(p)=="wel_sub" for p in subs): roster_category="wel_sub"
    elif any(status_by_name.get(p) in ("recurring_sub","former_sub") for p in subs): roster_category="recurring_sub"
    else: roster_category="occasional_sub"

    team_summary=next((s for s in segments if s.get("type")=="team-summary" and s.get("attributes",{}).get("teamId")==team_id),None)
    opp_summary=next((s for s in segments if s.get("type")=="team-summary" and s.get("attributes",{}).get("teamId")!=team_id),None)
    if not team_summary or not opp_summary: raise ValueError("team-summary manquant")
    sf=int(getv(team_summary.get("stats",{}),"roundsWon",0) or 0)
    sa=int(getv(team_summary.get("stats",{}),"roundsLost",0) or 0)
    result="W" if team_summary.get("metadata",{}).get("hasWon") else ("D" if sf==sa else "L")
    played_at=md.get("dateStarted") or datetime.now(timezone.utc).isoformat()

    if existing_series_id:
        s=con.execute("SELECT * FROM series WHERE id=?", (existing_series_id,)).fetchone()
        if not s: raise ValueError("Série existante introuvable")
        sid=s["id"]
        if map_index is None:
            map_index=(con.execute("SELECT COALESCE(MAX(map_index),0)+1 n FROM maps WHERE series_id=?",(sid,)).fetchone()["n"])
    else:
        if not event_name.strip() or not opponent.strip(): raise ValueError("Event et adversaire sont requis pour une nouvelle série")
        event=con.execute("SELECT * FROM events WHERE name=?",(event_name.strip(),)).fetchone()
        if not event:
            con.execute("INSERT INTO events(slug,name,competition) VALUES(?,?,?)", (slugify(event_name),event_name.strip(),(competition or event_name).strip()))
            event_id=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        else: event_id=event["id"]
        code=series_code.strip() or f"admin-{slugify(event_name)}-{slugify(opponent)}-{played_at[:10]}"
        key=f"admin::{code}"
        if con.execute("SELECT 1 FROM series WHERE series_key=?",(key,)).fetchone():
            raise ValueError("Series code déjà utilisé. Choisis la série existante ou change le code.")
        con.execute("INSERT INTO series(event_id,series_key,stage,opponent,played_at,best_of,maps_won,maps_lost,result,roster_category) VALUES(?,?,?,?,?,?,0,0,'N/A',?)",
                    (event_id,key,stage.strip() or None,opponent.strip(),played_at,int(best_of or 1),"core" if roster_category=="core" else "with_subs"))
        sid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        map_index=map_index or 1

    comp=[]
    for p in psummary:
        if p.get("metadata",{}).get("teamId")==team_id:
            comp.append(p.get("metadata",{}).get("agentName") or "Unknown")
    comp_key=" / ".join(sorted(comp))
    source_path=f"admin/{match_id}.json"
    con.execute("""INSERT INTO maps(series_id,match_id,map_index,map_name,map_image_url,played_at,duration_ms,raw_rounds,official_rounds,team_id,start_side,
                 score_for,score_against,result,roster_category,composition_key,data_quality,stats_complete,source_path,raw_json)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid,match_id,map_index,md.get("mapName") or "Unknown",md.get("mapImageUrl"),played_at,md.get("duration"),md.get("rounds"),md.get("rounds"),team_id,round_side(segments,1,team_id),
                 sf,sa,result,roster_category,comp_key,"complete",1,source_path,raw_text))
    map_id=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    pist=pistol_metrics(segments,team_id)
    con.execute("""INSERT INTO map_pistols(map_id,pistol_wins,pistol_played,attack_wins,attack_played,defense_wins,defense_played,conversion_wins,conversion_opportunities,first_half_result,second_half_result)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (map_id,pist["pistol_wins"],pist["pistol_played"],pist["attack_wins"],pist["attack_played"],pist["defense_wins"],pist["defense_played"],pist["conversion_wins"],pist["conversion_opportunities"],pist["first_half_result"],pist["second_half_result"]))

    canonical_names={}
    player_ids={r["canonical_name"]:r["id"] for r in con.execute("SELECT id,canonical_name FROM players")}
    for p in psummary:
        if p.get("metadata",{}).get("teamId") != team_id: continue
        account=p.get("attributes",{}).get("platformUserIdentifier"); canonical=actual_by_account[account]; canonical_names[account]=canonical
        pid=player_ids.get(canonical) or ensure_player(con,canonical); player_ids[canonical]=pid
        st=p.get("stats",{}); rank=getv(st,"rank"); tier=(st.get("rank",{}).get("metadata",{}) or {}).get("tierId") if isinstance(st.get("rank"),dict) else None
        con.execute("""INSERT INTO player_map_stats(map_id,player_id,account_riot_id,agent,agent_image_url,agent_portrait_url,rank,rank_tier_id,kills,deaths,assists,kd,acs,adr,kast,first_kills,first_deaths,damage_delta_per_round,headshot_pct,plants,defuses)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (map_id,pid,account,p.get("metadata",{}).get("agentName"),p.get("metadata",{}).get("agentImageUrl"),p.get("metadata",{}).get("agentPortraitUrl") or p.get("metadata",{}).get("agentImageUrl"),rank,tier,
                     getv(st,"kills"),getv(st,"deaths"),getv(st,"assists"),getv(st,"kdRatio"),getv(st,"scorePerRound"),getv(st,"damagePerRound"),getv(st,"kast") or getv(st,"kAST"),getv(st,"firstKills"),getv(st,"firstDeaths"),getv(st,"damageDeltaPerRound"),getv(st,"hsAccuracy"),getv(st,"plants"),getv(st,"defuses")))

    if subs:
        if len(subs)==1 and len(main_missing)==1: pairs=[(subs[0],main_missing[0],"exact")]
        else: pairs=[(sub,None,"ambiguous") for sub in subs]
        for sub,replaced,confidence in pairs:
            con.execute("INSERT INTO substitutions(map_id,sub_player_id,replaced_player_id,confidence,note) VALUES(?,?,?,?,?)",
                        (map_id,player_ids[sub],player_ids.get(replaced) if replaced else None,confidence,None if confidence=="exact" else f"Missing core: {', '.join(main_missing)}"))

    upsert_map_caches(con,map_id,raw_text,team_id,canonical_names)

    # Refresh series and event aggregates.
    agg=con.execute("SELECT SUM(result='W') w,SUM(result='L') l,COUNT(*) n,MIN(played_at) first FROM maps WHERE series_id=?",(sid,)).fetchone()
    sr="W" if agg["w"]>agg["l"] else ("L" if agg["l"]>agg["w"] else "D")
    rc="core" if con.execute("SELECT COUNT(*) c FROM maps WHERE series_id=? AND roster_category<>'core'",(sid,)).fetchone()["c"]==0 else "with_subs"
    con.execute("UPDATE series SET maps_won=?,maps_lost=?,result=?,roster_category=?,played_at=? WHERE id=?",(agg["w"],agg["l"],sr,rc,agg["first"],sid))
    event_id=con.execute("SELECT event_id FROM series WHERE id=?",(sid,)).fetchone()["event_id"]
    dates=con.execute("SELECT MIN(played_at) a,MAX(played_at) b FROM series WHERE event_id=? AND played_at IS NOT NULL",(event_id,)).fetchone()
    con.execute("UPDATE events SET first_date=?,last_date=? WHERE id=?",(dates["a"],dates["b"],event_id))

    raw_dir=ROOT/"data"/"private_raw"; raw_dir.mkdir(parents=True,exist_ok=True)
    (raw_dir/f"{match_id}.json").write_text(raw_text,encoding="utf-8")
    return {"map_id":map_id,"series_id":sid,"map_name":md.get("mapName"),"score":f"{sf}-{sa}","result":result}
