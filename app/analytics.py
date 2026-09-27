from __future__ import annotations

import json


def getv(stats, key, default=None):
    v = stats.get(key)
    return v.get("value", default) if isinstance(v, dict) else default


def team_map_insights_from_raw(raw_json: str, team_id: str):
    try:
        data = json.loads(raw_json)["data"]
    except Exception:
        return {"trades":0,"assists":0,"plants":0,"defuses":0,"clutches":0,"survived":0,"first_kills":0,"first_deaths":0,"kast":0,"attack_wins":0,"attack_played":0,"defense_wins":0,"defense_played":0}

    player_summaries=[]
    side_by_round={}
    winner_by_round={}
    for seg in data.get("segments", []):
        typ=seg.get("type")
        md=seg.get("metadata", {})
        if typ=="player-summary" and md.get("teamId")==team_id:
            player_summaries.append(seg)
        elif typ=="player-round" and md.get("teamId")==team_id:
            r=seg.get("attributes",{}).get("round")
            if r is not None and r not in side_by_round:
                side_by_round[r]=md.get("teamSide")
        elif typ=="round-summary":
            r=seg.get("attributes",{}).get("round")
            winner_by_round[r]=getv(seg.get("stats",{}),"winningTeam")

    agg={"trades":0,"assists":0,"plants":0,"defuses":0,"clutches":0,"survived":0,"first_kills":0,"first_deaths":0,"kast":0,"attack_wins":0,"attack_played":0,"defense_wins":0,"defense_played":0}
    kasts=[]
    for seg in player_summaries:
        st=seg.get("stats",{})
        for k in ("traded","assists","plants","defuses","clutches","survived","firstKills","firstDeaths"):
            val=getv(st,k,0) or 0
            dest={"firstKills":"first_kills","firstDeaths":"first_deaths","traded":"trades"}.get(k,k)
            agg[dest]+=val
        kv=getv(st,"kast",getv(st,"kAST",None))
        if kv is not None: kasts.append(float(kv))
    agg["kast"]=sum(kasts)/len(kasts) if kasts else 0
    for rnd,winner in winner_by_round.items():
        side=side_by_round.get(rnd)
        if side=="attacker":
            agg["attack_played"]+=1
            if winner==team_id: agg["attack_wins"]+=1
        elif side=="defender":
            agg["defense_played"]+=1
            if winner==team_id: agg["defense_wins"]+=1
    return agg


def leaderboard_from_raw(raw_json: str, team_id: str, canonical_names=None):
    canonical_names = canonical_names or {}
    try:
        data = json.loads(raw_json)["data"]
    except Exception:
        return []
    out = []
    for seg in data.get("segments", []):
        if seg.get("type") != "player-summary":
            continue
        md = seg.get("metadata", {})
        st = seg.get("stats", {})
        riot_id=seg.get("attributes", {}).get("platformUserIdentifier")
        is_ours=md.get("teamId") == team_id
        out.append({
            "riot_id": riot_id,
            "display_name": canonical_names.get(riot_id, riot_id) if is_ours else riot_id,
            "team_id": md.get("teamId"),
            "is_team": is_ours,
            "agent": md.get("agentName"),
            "agent_icon": md.get("agentImageUrl"),
            "kills": getv(st, "kills", 0),
            "deaths": getv(st, "deaths", 0),
            "assists": getv(st, "assists", 0),
            "acs": getv(st, "scorePerRound", 0),
            "kast": getv(st, "kast", getv(st, "kAST", 0)),
            "first_kills": getv(st, "firstKills", 0),
            "first_deaths": getv(st, "firstDeaths", 0),
            "traded": getv(st, "traded", 0),
            "score": getv(st, "score", 0),
        })
    out.sort(key=lambda x: (not x["is_team"], -(x["score"] or 0), -(x["kills"] or 0)))
    return out


def cached_insights(con, map_row):
    row = con.execute("SELECT payload_json FROM map_team_insights_cache WHERE map_id=?", (map_row["id"],)).fetchone()
    if row:
        return json.loads(row["payload_json"])
    raw = map_row["raw_json"] if "raw_json" in map_row.keys() else ""
    return team_map_insights_from_raw(raw or "", map_row["team_id"])


def cached_leaderboard(con, map_row, canonical_names=None):
    row = con.execute("SELECT payload_json FROM map_leaderboard_cache WHERE map_id=?", (map_row["id"],)).fetchone()
    if row:
        return json.loads(row["payload_json"])
    raw = map_row["raw_json"] if "raw_json" in map_row.keys() else ""
    return leaderboard_from_raw(raw or "", map_row["team_id"], canonical_names)


def upsert_map_caches(con, map_id: int, raw_json: str, team_id: str, canonical_names=None):
    insights = team_map_insights_from_raw(raw_json, team_id)
    leaderboard = leaderboard_from_raw(raw_json, team_id, canonical_names or {})
    con.execute("INSERT OR REPLACE INTO map_team_insights_cache(map_id,payload_json) VALUES(?,?)", (map_id, json.dumps(insights, separators=(",",":"))))
    con.execute("INSERT OR REPLACE INTO map_leaderboard_cache(map_id,payload_json) VALUES(?,?)", (map_id, json.dumps(leaderboard, separators=(",",":"))))
