from __future__ import annotations

import json
import os
import re
import base64
import hashlib
import hmac
import secrets
from collections import defaultdict
from fastapi import FastAPI, Request, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import ROOT
from .db import connect
from .analytics import cached_insights, cached_leaderboard
from .admin_import import import_official_map

app = FastAPI(title="Team Dashboard")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")


_AGENT_UUID_RE = re.compile(r"/agents/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/", re.I)


def valorant_agent_asset(url, filename):
    """Use Valorant-API's current media CDN for an agent asset when its UUID is known."""
    if not url:
        return url
    match = _AGENT_UUID_RE.search(str(url))
    if not match:
        return url
    return f"https://media.valorant-api.com/agents/{match.group(1)}/{filename}"


templates.env.filters["valorant_icon"] = lambda url: valorant_agent_asset(url, "displayicon.png")
templates.env.filters["valorant_portrait"] = lambda url: valorant_agent_asset(url, "fullportrait.png")


def pct(w, total):
    return round((w / total) * 100, 1) if total else 0.0


def status_label(s):
    return {
        "main": "Core",
        "recurring_sub": "Recurring sub",
        "former_sub": "Former recurring sub",
        "wel_sub": "WEL sub",
        "occasional_sub": "Occasional sub",
    }.get(s, s)


def roster_label(s):
    return {
        "core": "Core",
        "with_subs": "With subs",
        "recurring_sub": "Recurring sub",
        "wel_sub": "WEL sub",
        "occasional_sub": "Occasional sub",
        "N/A": "N/A",
    }.get(s, s.replace("_", " ").title() if s else "—")


def getv(stats, key, default=None):
    v = stats.get(key)
    return v.get("value", default) if isinstance(v, dict) else default


DUELISTS = {"Jett", "Raze", "Neon", "Waylay", "Phoenix", "Reyna", "Yoru", "Iso"}
ENTRY = {"Jett", "Raze", "Neon", "Waylay"}
RECON = {"Sova", "Fade"}
INITIATORS = {"Sova", "Fade", "Breach", "Skye", "KAY/O", "Gekko", "Tejo"}
CONTROLLERS = {"Omen", "Brimstone", "Viper", "Astra", "Harbor", "Clove"}
SENTINELS = {"Cypher", "Killjoy", "Sage", "Chamber", "Deadlock", "Vyse", "Veto"}
ENTRY_PRIORITY = ["Neon", "Jett", "Waylay", "Raze"]
DUEL_PRIORITY = ["Phoenix", "Yoru", "Iso", "Reyna"]
RECON_PRIORITY = ["Sova", "Fade"]
INIT_PRIORITY = ["Breach", "KAY/O", "Gekko", "Skye", "Tejo"]
CTRL_PRIORITY = ["Omen", "Astra", "Brimstone", "Harbor", "Clove", "Viper"]
SENTI_PRIORITY = ["Cypher", "Killjoy", "Veto", "Vyse", "Sage", "Chamber", "Deadlock"]

CORE_PLAYER_ORDER = ["Duke", "Lindorm", "Lugia", "LJPH", "CeCe"]
# Keep role icons packaged with the app. Remote role assets caused broken
# rendering for some local setups, while these static files are served by FastAPI.
ROLE_ICONS = {
    "duelist": "/static/roles/duelist.png",
    "initiator": "/static/roles/initiator.png",
    "controller": "/static/roles/controller.png",
    "sentinel": "/static/roles/sentinel.png",
}
CORE_PLAYER_META = {
    "Duke": {"role_label": "Duelist", "role_key": "duelist", "portrait_pos": "51% 23%"},
    "Lindorm": {"role_label": "Flex", "role_key": "flex", "portrait_pos": "50% 22%"},
    "Lugia": {"role_label": "Recon", "role_key": "initiator", "portrait_pos": "48% 19%"},
    "LJPH": {"role_label": "Controller / IGL", "role_key": "controller", "portrait_pos": "52% 20%"},
    "CeCe": {"role_label": "Sentinel", "role_key": "sentinel", "portrait_pos": "50% 20%"},
}
for _meta in CORE_PLAYER_META.values():
    _meta["role_icon"] = ROLE_ICONS.get(_meta["role_key"])


def _ordered_from(names, priority):
    return [x for x in priority if x in names] + sorted([x for x in names if x not in priority])


def order_comp_agents(agents):
    """Apply the coach-defined visual role order for 5-agent comps."""
    by_name = {a["agent"]: dict(a) for a in agents}
    names = set(by_name)
    entries = _ordered_from(names & ENTRY, ENTRY_PRIORITY)
    duel_nonentry = _ordered_from((names & DUELISTS) - ENTRY, DUEL_PRIORITY)
    recon = _ordered_from(names & RECON, RECON_PRIORITY)
    inits = _ordered_from((names & INITIATORS) - RECON, INIT_PRIORITY)
    ctrls = _ordered_from(names & CONTROLLERS, CTRL_PRIORITY)
    sentis = _ordered_from(names & SENTINELS, SENTI_PRIORITY)
    used = []

    # Exact role-order rules requested by the coach.
    if len(entries) >= 2:
        used = entries[:2] + (recon[:1] or inits[:1]) + ctrls[:1] + sentis[:1]
    elif len(entries) >= 1 and duel_nonentry:
        used = entries[:1] + (recon[:1] or inits[:1]) + duel_nonentry[:1] + ctrls[:1] + sentis[:1]
    elif len(recon) + len(inits) >= 2:
        lead = entries[:1] or duel_nonentry[:1]
        used = lead + (recon[:1] or inits[:1])
        second_init_pool = [x for x in recon + inits if x not in used]
        used += second_init_pool[:1] + ctrls[:1] + sentis[:1]
    elif len(ctrls) >= 2:
        lead = entries[:1] or duel_nonentry[:1]
        used = lead + (recon[:1] or inits[:1]) + ctrls[:2] + sentis[:1]
    elif len(sentis) >= 2:
        lead = entries[:1] or duel_nonentry[:1]
        used = lead + (recon[:1] or inits[:1]) + ctrls[:1] + sentis[:2]
    else:
        used = entries + duel_nonentry + recon + inits + ctrls + sentis

    # Never drop an unusual agent/role combination.
    for n in sorted(names):
        if n not in used:
            used.append(n)
    return [by_name[n] for n in used if n in by_name]


def team_map_insights(raw_json, team_id):
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


def leaderboard_from_raw(raw_json, team_id, canonical_names=None):
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


ADMIN_COOKIE = "team_admin_session"

def _admin_codes():
    raw = os.environ.get("ADMIN_CODES") or os.environ.get("ADMIN_CODE") or ""
    codes = [x.strip() for x in raw.split(",") if x.strip()]
    local_file = ROOT / "data" / "admin_codes.txt"
    if not codes and local_file.exists():
        codes = [x.strip() for x in local_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    return codes

def _admin_secret():
    explicit = os.environ.get("ADMIN_COOKIE_SECRET")
    if explicit:
        return explicit.encode("utf-8")
    codes = _admin_codes()
    seed = "|".join(codes) if codes else "admin-not-configured"
    return hashlib.sha256((seed + "|team-dashboard-admin-v1").encode("utf-8")).digest()

def _admin_cookie_value():
    sig = hmac.new(_admin_secret(), b"authorized", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")

def is_admin(request: Request):
    cookie = request.cookies.get(ADMIN_COOKIE, "")
    return bool(cookie) and secrets.compare_digest(cookie, _admin_cookie_value())

def _require_admin(request: Request, next_path: str = "/admin/"):
    if not is_admin(request):
        return RedirectResponse(url=f"/admin/?next={next_path}", status_code=303)
    return None

templates.env.globals.update(pct=pct, status_label=status_label, roster_label=roster_label)


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    with connect() as con:
        map_totals = con.execute("""SELECT COUNT(*) maps,SUM(result='W') wins,SUM(result='L') losses,SUM(score_for) rounds_for,SUM(score_against) rounds_against FROM maps""").fetchone()
        series_totals = con.execute("""SELECT COUNT(*) series,SUM(result='W') wins,SUM(result='L') losses FROM series WHERE is_bye=0""").fetchone()
        pistol = con.execute("""SELECT SUM(pistol_wins) wins,SUM(pistol_played) played,SUM(attack_wins) attack_wins,SUM(attack_played) attack_played,SUM(defense_wins) defense_wins,SUM(defense_played) defense_played,SUM(conversion_wins) conversion_wins,SUM(conversion_opportunities) conversion_opportunities FROM map_pistols""").fetchone()
        roster = con.execute("""SELECT roster_category,COUNT(*) maps,SUM(result='W') wins,SUM(result='L') losses FROM maps GROUP BY roster_category ORDER BY maps DESC""").fetchall()
        map_roster_split = con.execute("""SELECT CASE WHEN roster_category='core' THEN 'core' ELSE 'with_subs' END context,COUNT(*) played,SUM(result='W') wins,SUM(result='L') losses FROM maps GROUP BY context ORDER BY context""").fetchall()
        series_roster_split = con.execute("""SELECT CASE WHEN roster_category='core' THEN 'core' ELSE 'with_subs' END context,COUNT(*) played,SUM(result='W') wins,SUM(result='L') losses FROM series WHERE is_bye=0 GROUP BY context ORDER BY context""").fetchall()
        map_pool = con.execute("""SELECT m.map_name,MAX(m.map_image_url) map_image_url,COUNT(*) games,SUM(m.result='W') wins,SUM(m.result='L') losses,SUM(p.pistol_wins) pistol_wins,SUM(p.pistol_played) pistol_played,SUM(m.score_for)-SUM(m.score_against) round_diff FROM maps m JOIN map_pistols p ON p.map_id=m.id GROUP BY m.map_name ORDER BY games DESC,m.map_name""").fetchall()
        recent = con.execute("""SELECT s.*,e.name event_name FROM series s JOIN events e ON e.id=s.event_id WHERE s.is_bye=0 ORDER BY s.played_at DESC LIMIT 6""").fetchall()
        open_issues = con.execute("SELECT COUNT(*) FROM data_issues WHERE resolved=0").fetchone()[0]
    return templates.TemplateResponse(request, "overview.html", {"map_totals":map_totals,"series_totals":series_totals,"pistol":pistol,"roster":roster,"map_roster_split":map_roster_split,"series_roster_split":series_roster_split,"map_pool":map_pool,"recent":recent,"open_issues":open_issues})


@app.get("/players", response_class=HTMLResponse)
def players_index(request: Request):
    with connect() as con:
        rows = con.execute("""
            SELECT p.*,COUNT(pms.id) maps_played,COUNT(DISTINCT m.series_id) series_played,
                   SUM(m.result='W') wins,SUM(m.result='L') losses,
                   SUM(COALESCE(pms.kills,0)) kills,SUM(COALESCE(pms.deaths,0)) deaths,SUM(COALESCE(pms.assists,0)) assists
            FROM players p LEFT JOIN player_map_stats pms ON pms.player_id=p.id LEFT JOIN maps m ON m.id=pms.map_id
            GROUP BY p.id ORDER BY CASE p.roster_status WHEN 'main' THEN 1 WHEN 'recurring_sub' THEN 2 WHEN 'wel_sub' THEN 3 WHEN 'former_sub' THEN 4 ELSE 5 END,p.canonical_name
        """).fetchall()
        players=[]
        for r in rows:
            d=dict(r)
            meta=CORE_PLAYER_META.get(r["canonical_name"], {})
            d.update(meta)
            d["core_order"] = CORE_PLAYER_ORDER.index(r["canonical_name"]) if r["canonical_name"] in CORE_PLAYER_ORDER else 99
            top=con.execute("""SELECT agent,MAX(agent_image_url) icon,COUNT(*) n FROM player_map_stats WHERE player_id=? GROUP BY agent ORDER BY n DESC,agent LIMIT 1""",(r["id"],)).fetchone()
            d["top_agent"] = top["agent"] if top else None
            d["top_agent_icon"] = top["icon"] if top else None
            d["top_agent_portrait"] = valorant_agent_asset(top["icon"], "fullportrait.png") if top else None
            players.append(d)
        players.sort(key=lambda x: (0 if x["roster_status"]=="main" else 1, x.get("core_order",99), x["canonical_name"]))
    return templates.TemplateResponse(request,"players.html",{"players":players})


@app.get("/players/{slug}", response_class=HTMLResponse)
def player_profile(request: Request, slug: str):
    with connect() as con:
        player_row=con.execute("SELECT * FROM players WHERE slug=?",(slug,)).fetchone()
        if not player_row: raise HTTPException(404,"Player not found")
        player=dict(player_row)
        player.update(CORE_PLAYER_META.get(player["canonical_name"], {}))
        pid=player["id"]
        aliases=con.execute("SELECT * FROM player_aliases WHERE player_id=? ORDER BY id",(pid,)).fetchall()
        top_agent=con.execute("""SELECT agent,MAX(agent_image_url) icon,MAX(agent_portrait_url) portrait,COUNT(*) games FROM player_map_stats WHERE player_id=? GROUP BY agent ORDER BY games DESC,agent LIMIT 1""",(pid,)).fetchone()
        total_maps=con.execute("SELECT COUNT(*) FROM maps").fetchone()[0]
        summary=con.execute("""
            SELECT COUNT(*) maps_played,COUNT(DISTINCT m.series_id) series_played,SUM(m.result='W') wins,SUM(m.result='L') losses,
                   SUM(COALESCE(pms.kills,0)) kills,SUM(COALESCE(pms.deaths,0)) deaths,SUM(COALESCE(pms.assists,0)) assists,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.acs,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) acs,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.kast,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) kast,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.damage_delta_per_round,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) ddpr,
                   SUM(COALESCE(pms.first_kills,0)) first_kills,SUM(COALESCE(pms.first_deaths,0)) first_deaths
            FROM player_map_stats pms JOIN maps m ON m.id=pms.map_id WHERE pms.player_id=?
        """,(pid,)).fetchone()
        agents=con.execute("""
            SELECT pms.agent,MAX(pms.agent_image_url) agent_image_url,COUNT(*) games,SUM(m.result='W') wins,SUM(m.result='L') losses,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.acs,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) acs,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.kast,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) kast
            FROM player_map_stats pms JOIN maps m ON m.id=pms.map_id WHERE pms.player_id=? GROUP BY pms.agent ORDER BY games DESC,pms.agent
        """,(pid,)).fetchall()
        maps=con.execute("""
            SELECT m.map_name,MAX(m.map_image_url) map_image_url,COUNT(*) games,SUM(m.result='W') wins,SUM(m.result='L') losses,
                   SUM(COALESCE(pms.kills,0)) kills,SUM(COALESCE(pms.deaths,0)) deaths,SUM(COALESCE(pms.assists,0)) assists,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.acs,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) acs,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.kast,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) kast,
                   SUM(COALESCE(pms.first_kills,0)) first_kills,SUM(COALESCE(pms.first_deaths,0)) first_deaths,
                   SUM(CASE WHEN m.stats_complete=1 THEN COALESCE(pms.damage_delta_per_round,0)*m.raw_rounds ELSE 0 END)/NULLIF(SUM(CASE WHEN m.stats_complete=1 THEN m.raw_rounds ELSE 0 END),0) ddpr
            FROM player_map_stats pms JOIN maps m ON m.id=pms.map_id WHERE pms.player_id=? GROUP BY m.map_name ORDER BY games DESC,m.map_name
        """,(pid,)).fetchall()
        recent=con.execute("""
            SELECT m.*,s.id series_id,s.opponent,e.name event_name,pms.agent,pms.agent_image_url,pms.kills,pms.deaths,pms.assists,pms.acs,pms.kast,pms.account_riot_id
            FROM player_map_stats pms JOIN maps m ON m.id=pms.map_id JOIN series s ON s.id=m.series_id JOIN events e ON e.id=s.event_id
            WHERE pms.player_id=? ORDER BY m.played_at DESC LIMIT 5
        """,(pid,)).fetchall()
        subbed_for=con.execute("""SELECT rp.canonical_name replaced,COUNT(*) maps FROM substitutions sub LEFT JOIN players rp ON rp.id=sub.replaced_player_id WHERE sub.sub_player_id=? AND sub.confidence='exact' GROUP BY rp.id ORDER BY maps DESC""",(pid,)).fetchall()
        replaced_by=con.execute("""SELECT sp.canonical_name sub_name,COUNT(*) maps FROM substitutions sub JOIN players sp ON sp.id=sub.sub_player_id WHERE sub.replaced_player_id=? AND sub.confidence='exact' GROUP BY sp.id ORDER BY maps DESC""",(pid,)).fetchall()
    return templates.TemplateResponse(request,"player.html",{"player":player,"aliases":aliases,"summary":summary,"agents":agents,"maps":maps,"recent":recent,"total_maps":total_maps,"subbed_for":subbed_for,"replaced_by":replaced_by,"top_agent":top_agent})


def series_cards(con):
    rows=con.execute("""SELECT s.*,e.name event_name,e.competition FROM series s JOIN events e ON e.id=s.event_id ORDER BY CASE WHEN s.played_at IS NULL THEN 1 ELSE 0 END,s.played_at DESC,s.id DESC""").fetchall()
    out=[]
    for s in rows:
        maps=con.execute("SELECT * FROM maps WHERE series_id=? ORDER BY map_index,id",(s["id"],)).fetchall()
        map_out=[]
        for m in maps:
            agents=con.execute("SELECT agent,MAX(agent_image_url) agent_image_url FROM player_map_stats WHERE map_id=? GROUP BY agent",(m["id"],)).fetchall()
            map_out.append({"row":m,"agents":order_comp_agents(agents)})
        out.append({"row":s,"maps":map_out})
    return out


@app.get("/matches", response_class=HTMLResponse)
def matches(request: Request):
    with connect() as con: groups=series_cards(con)
    return templates.TemplateResponse(request,"matches.html",{"groups":groups})


@app.get("/matches/{series_id}", response_class=HTMLResponse)
def match_detail(request: Request, series_id:int):
    with connect() as con:
        s=con.execute("""SELECT s.*,e.name event_name,e.competition FROM series s JOIN events e ON e.id=s.event_id WHERE s.id=?""",(series_id,)).fetchone()
        if not s: raise HTTPException(404,"Match not found")
        maps=con.execute("SELECT * FROM maps WHERE series_id=? ORDER BY map_index,id",(series_id,)).fetchall()
        detail=[]
        for m in maps:
            agents=con.execute("SELECT agent,MAX(agent_image_url) agent_image_url FROM player_map_stats WHERE map_id=? GROUP BY agent",(m["id"],)).fetchall()
            canonical={r["account_riot_id"]:r["canonical_name"] for r in con.execute("""SELECT pms.account_riot_id,p.canonical_name FROM player_map_stats pms JOIN players p ON p.id=pms.player_id WHERE pms.map_id=?""",(m["id"],)).fetchall()}
            detail.append({"row":m,"agents":order_comp_agents(agents),"leaderboard":cached_leaderboard(con,m,canonical),"insights":cached_insights(con,m)})
    return templates.TemplateResponse(request,"match.html",{"series":s,"maps":detail})


@app.get("/maps", response_class=HTMLResponse)
def map_stats(request: Request):
    with connect() as con:
        rows=con.execute("""
            SELECT m.map_name,MAX(m.map_image_url) map_image_url,
              COUNT(*) all_games,SUM(m.result='W') all_wins,SUM(m.result='L') all_losses,SUM(m.score_for)-SUM(m.score_against) all_round_diff,
              SUM(p.pistol_wins) all_pistol_wins,SUM(p.pistol_played) all_pistols,SUM(p.attack_wins) all_atk_wins,SUM(p.attack_played) all_atk_pistols,SUM(p.defense_wins) all_def_wins,SUM(p.defense_played) all_def_pistols,
              SUM(m.roster_category='core') core_games,SUM(m.roster_category='core' AND m.result='W') core_wins,SUM(m.roster_category='core' AND m.result='L') core_losses,
              SUM(CASE WHEN m.roster_category='core' THEN m.score_for-m.score_against ELSE 0 END) core_round_diff,
              SUM(CASE WHEN m.roster_category='core' THEN p.pistol_wins ELSE 0 END) core_pistol_wins,SUM(CASE WHEN m.roster_category='core' THEN p.pistol_played ELSE 0 END) core_pistols,
              SUM(CASE WHEN m.roster_category='core' THEN p.attack_wins ELSE 0 END) core_atk_wins,SUM(CASE WHEN m.roster_category='core' THEN p.attack_played ELSE 0 END) core_atk_pistols,
              SUM(CASE WHEN m.roster_category='core' THEN p.defense_wins ELSE 0 END) core_def_wins,SUM(CASE WHEN m.roster_category='core' THEN p.defense_played ELSE 0 END) core_def_pistols,
              SUM(m.roster_category<>'core') sub_games,SUM(m.roster_category<>'core' AND m.result='W') sub_wins,SUM(m.roster_category<>'core' AND m.result='L') sub_losses,
              SUM(CASE WHEN m.roster_category<>'core' THEN m.score_for-m.score_against ELSE 0 END) sub_round_diff,
              SUM(CASE WHEN m.roster_category<>'core' THEN p.pistol_wins ELSE 0 END) sub_pistol_wins,SUM(CASE WHEN m.roster_category<>'core' THEN p.pistol_played ELSE 0 END) sub_pistols,
              SUM(CASE WHEN m.roster_category<>'core' THEN p.attack_wins ELSE 0 END) sub_atk_wins,SUM(CASE WHEN m.roster_category<>'core' THEN p.attack_played ELSE 0 END) sub_atk_pistols,
              SUM(CASE WHEN m.roster_category<>'core' THEN p.defense_wins ELSE 0 END) sub_def_wins,SUM(CASE WHEN m.roster_category<>'core' THEN p.defense_played ELSE 0 END) sub_def_pistols
            FROM maps m JOIN map_pistols p ON p.map_id=m.id GROUP BY m.map_name ORDER BY all_games DESC,m.map_name
        """).fetchall()
        enriched=[]
        for r in rows:
            d=dict(r)
            side={"core":[0,0,0,0],"subs":[0,0,0,0],"all":[0,0,0,0]}
            raw_rows=con.execute("SELECT id,raw_json,team_id,roster_category FROM maps WHERE map_name=?",(r["map_name"],)).fetchall()
            for rm in raw_rows:
                ins=cached_insights(con,rm)
                for key in ("all", "core" if rm["roster_category"]=="core" else "subs"):
                    side[key][0]+=ins["attack_wins"]; side[key][1]+=ins["attack_played"]; side[key][2]+=ins["defense_wins"]; side[key][3]+=ins["defense_played"]
            for key,vals in side.items():
                d[f"{key}_atk_round_wins"],d[f"{key}_atk_rounds"],d[f"{key}_def_round_wins"],d[f"{key}_def_rounds"]=vals
            # Analyst-facing expandable context: current Core comp + five most recent officials on the map.
            top_comp=con.execute("""
                SELECT composition_key,COUNT(*) games,SUM(result='W') wins,MIN(id) sample_map_id
                FROM maps WHERE map_name=? AND roster_category='core'
                GROUP BY composition_key ORDER BY games DESC,wins DESC LIMIT 1
            """,(r["map_name"],)).fetchone()
            d["top_comp"] = dict(top_comp) if top_comp else None
            if top_comp:
                ag=con.execute("SELECT agent,MAX(agent_image_url) agent_image_url FROM player_map_stats WHERE map_id=? GROUP BY agent",(top_comp["sample_map_id"],)).fetchall()
                d["top_comp_agents"] = order_comp_agents(ag)
            else:
                d["top_comp_agents"] = []
            d["recent"] = con.execute("""
                SELECT m.id,m.result,m.score_for,m.score_against,m.played_at,m.roster_category,s.id series_id,s.opponent,e.name event_name
                FROM maps m JOIN series s ON s.id=m.series_id JOIN events e ON e.id=s.event_id
                WHERE m.map_name=? ORDER BY m.played_at DESC,m.id DESC LIMIT 5
            """,(r["map_name"],)).fetchall()
            enriched.append(d)
    return templates.TemplateResponse(request,"maps.html",{"maps":enriched})


@app.get("/compositions", response_class=HTMLResponse)
def compositions(request: Request):
    with connect() as con:
        map_rows=con.execute("SELECT map_name,MAX(map_image_url) map_image_url,COUNT(*) games,SUM(result='W') wins,SUM(result='L') losses FROM maps GROUP BY map_name ORDER BY games DESC,map_name").fetchall()
        groups=[]
        for mr in map_rows:
            contexts=[]
            for context,where in (("core","m.roster_category='core'"),("subs","m.roster_category<>'core'"),("all","1=1")):
                comps=con.execute(f"""
                    SELECT m.composition_key,COUNT(*) games,SUM(m.result='W') wins,SUM(m.result='L') losses,MIN(m.played_at) first_used,MAX(m.played_at) last_used,
                           SUM(p.pistol_wins) pistol_wins,SUM(p.pistol_played) pistol_played,MIN(m.id) sample_map_id
                    FROM maps m JOIN map_pistols p ON p.map_id=m.id WHERE m.map_name=? AND {where}
                    GROUP BY m.composition_key ORDER BY games DESC,last_used DESC
                """,(mr["map_name"],)).fetchall()
                comp_out=[]
                for c in comps:
                    agents=con.execute("SELECT agent,MAX(agent_image_url) agent_image_url FROM player_map_stats WHERE map_id=? GROUP BY agent",(c["sample_map_id"],)).fetchall()
                    comp_out.append({"row":c,"agents":order_comp_agents(agents)})
                contexts.append({"key":context,"comps":comp_out})
            groups.append({"map":mr,"contexts":contexts})
    return templates.TemplateResponse(request,"compositions.html",{"groups":groups})


@app.get("/events", response_class=HTMLResponse)
def events(request: Request):
    with connect() as con:
        rows=con.execute("""
            SELECT e.*,SUM(CASE WHEN s.is_bye=0 THEN 1 ELSE 0 END) played_series,SUM(CASE WHEN s.is_bye=0 AND s.result='W' THEN 1 ELSE 0 END) wins,SUM(CASE WHEN s.is_bye=0 AND s.result='L' THEN 1 ELSE 0 END) losses,SUM(CASE WHEN s.is_bye=1 THEN 1 ELSE 0 END) byes,
                   SUM(CASE WHEN lower(COALESCE(s.stage,'')) LIKE '%regular%' AND s.is_bye=0 THEN 1 ELSE 0 END) regular_played,
                   SUM(CASE WHEN lower(COALESCE(s.stage,'')) LIKE '%regular%' AND s.is_bye=0 AND s.result='W' THEN 1 ELSE 0 END) regular_wins,
                   SUM(CASE WHEN lower(COALESCE(s.stage,'')) LIKE '%playoff%' AND s.is_bye=0 THEN 1 ELSE 0 END) playoff_played,
                   SUM(CASE WHEN lower(COALESCE(s.stage,'')) LIKE '%playoff%' AND s.is_bye=0 AND s.result='W' THEN 1 ELSE 0 END) playoff_wins
            FROM events e LEFT JOIN series s ON s.event_id=e.id GROUP BY e.id ORDER BY COALESCE(e.last_date,'0000') DESC
        """).fetchall()
    return templates.TemplateResponse(request,"events.html",{"events":rows})


@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request,event_id:int):
    with connect() as con:
        event=con.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not event: raise HTTPException(404,"Event not found")
        rows=con.execute("""SELECT s.* FROM series s WHERE s.event_id=? ORDER BY CASE WHEN s.played_at IS NULL THEN 1 ELSE 0 END,s.played_at DESC,s.id DESC""",(event_id,)).fetchall()
        groups=defaultdict(list)
        for s in rows:
            maps=con.execute("SELECT * FROM maps WHERE series_id=? ORDER BY map_index,id",(s["id"],)).fetchall()
            d={"row":s,"maps":maps}
            if event["competition"]=="Valorant Premier":
                key="Playoffs" if "playoff" in (s["stage"] or "").lower() else "Regular Season"
            else:
                key="Event matches"
            groups[key].append(d)
    ordered=[]
    for key in (["Playoffs","Regular Season"] if event["competition"]=="Valorant Premier" else ["Event matches"]):
        if groups.get(key): ordered.append((key,groups[key]))
    return templates.TemplateResponse(request,"event.html",{"event":event,"groups":ordered})


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    with connect() as con:
        rows=con.execute("""SELECT substr(m.played_at,1,7) month,COUNT(*) maps,SUM(m.result='W') wins,SUM(m.result='L') losses,SUM(p.pistol_wins) pistol_wins,SUM(p.pistol_played) pistol_played,SUM(m.score_for)-SUM(m.score_against) round_diff FROM maps m JOIN map_pistols p ON p.map_id=m.id GROUP BY month ORDER BY month""").fetchall()
    return templates.TemplateResponse(request,"history.html",{"months":rows})


@app.get("/data-health", response_class=HTMLResponse)
def data_health(request: Request):
    guard = _require_admin(request, "/data-health")
    if guard:
        return guard
    with connect() as con:
        issues=con.execute("SELECT * FROM data_issues ORDER BY resolved,CASE severity WHEN 'error' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,id").fetchall()
        stats={"maps":con.execute("SELECT COUNT(*) FROM maps").fetchone()[0],"series":con.execute("SELECT COUNT(*) FROM series").fetchone()[0],"events":con.execute("SELECT COUNT(*) FROM events").fetchone()[0],"players":con.execute("SELECT COUNT(*) FROM players").fetchone()[0],"open":con.execute("SELECT COUNT(*) FROM data_issues WHERE resolved=0").fetchone()[0]}
    return templates.TemplateResponse(request,"data_health.html",{"issues":issues,"stats":stats,"admin_view":True})


@app.get("/admin", include_in_schema=False)
def admin_redirect():
    return RedirectResponse(url="/admin/", status_code=307)


@app.get("/admin/", response_class=HTMLResponse)
def admin_page(request: Request, ok: str | None = None, next: str | None = None):
    if not is_admin(request):
        return templates.TemplateResponse(request,"admin_login.html",{
            "next_path": next or "/admin/",
            "configured": bool(_admin_codes()),
            "error": None,
        })
    with connect() as con:
        recent_series=con.execute("""SELECT s.id,s.opponent,s.stage,e.name event_name FROM series s JOIN events e ON e.id=s.event_id WHERE s.is_bye=0 ORDER BY s.played_at DESC,s.id DESC LIMIT 30""").fetchall()
        counts={"maps":con.execute("SELECT COUNT(*) c FROM maps").fetchone()["c"],"series":con.execute("SELECT COUNT(*) c FROM series WHERE is_bye=0").fetchone()["c"],"players":con.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]}
    return templates.TemplateResponse(request,"admin.html",{
        "recent_series":recent_series,"counts":counts,"message":ok,
        "admin_view":True,"vercel_readonly":bool(os.environ.get("VERCEL"))
    })


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, code: str = Form(""), next_path: str = Form("/admin/")):
    codes = _admin_codes()
    valid = bool(codes) and any(secrets.compare_digest(code, c) for c in codes)
    if not valid:
        return templates.TemplateResponse(request,"admin_login.html",{
            "next_path": next_path or "/admin/",
            "configured": bool(codes),
            "error": "Invalid admin code." if codes else "No admin code is configured yet.",
        }, status_code=401)
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/admin/"
    response = RedirectResponse(url=safe_next, status_code=303)
    response.set_cookie(
        ADMIN_COOKIE, _admin_cookie_value(), max_age=60*60*12, httponly=True,
        secure=bool(os.environ.get("VERCEL")), samesite="lax", path="/"
    )
    return response


@app.post("/admin/logout")
def admin_logout():
    response = RedirectResponse(url="/admin/", status_code=303)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return response


@app.post("/admin/import", response_class=HTMLResponse)
async def admin_import_map(request: Request,
    existing_series_id: str = Form(""), event_name: str = Form(""), competition: str = Form(""), stage: str = Form(""),
    opponent: str = Form(""), best_of: int = Form(1), series_code: str = Form(""), map_index: str = Form(""),
    explicit_team_id: str = Form(""), overrides_text: str = Form(""), json_text: str = Form(""), json_file: UploadFile | None = File(None)):
    guard = _require_admin(request, "/admin/")
    if guard:
        return guard
    if os.environ.get("VERCEL"):
        raise HTTPException(403, "Hosted admin is read-only. Import locally, then prepare and redeploy the compact database.")
    raw=json_text.strip()
    if json_file and json_file.filename:
        raw=(await json_file.read()).decode("utf-8",errors="replace").strip()
    error=None; message=None
    if not raw:
        error="Ajoute un fichier JSON ou colle le JSON Tracker."
    else:
        try:
            with connect() as con:
                result=import_official_map(con,raw,existing_series_id=int(existing_series_id) if existing_series_id else None,event_name=event_name,competition=competition,stage=stage,opponent=opponent,best_of=best_of,series_code=series_code,map_index=int(map_index) if map_index else None,explicit_team_id=explicit_team_id or None,overrides_text=overrides_text)
            message=f"Imported {result['map_name']} {result['score']} ({result['result']}) · series #{result['series_id']}"
        except Exception as e:
            error=str(e)
    with connect() as con:
        recent_series=con.execute("""SELECT s.id,s.opponent,s.stage,e.name event_name FROM series s JOIN events e ON e.id=s.event_id WHERE s.is_bye=0 ORDER BY s.played_at DESC,s.id DESC LIMIT 30""").fetchall()
        counts={"maps":con.execute("SELECT COUNT(*) c FROM maps").fetchone()["c"],"series":con.execute("SELECT COUNT(*) c FROM series WHERE is_bye=0").fetchone()["c"],"players":con.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]}
    return templates.TemplateResponse(request,"admin.html",{
        "recent_series":recent_series,"counts":counts,"message":message,"error":error,
        "admin_view":True,"vercel_readonly":False
    })
