from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import SOURCE_ZIP, DB_PATH
from app.db import init_db, connect

TEAM_NAME = "W1Z"
MAIN_PLAYERS = ["Lugia", "Lindorm", "LJPH", "CeCe", "Duke"]
PLAYER_SEEDS = {
    "Lugia": ("main", 1, ["Lugia#707"]),
    "Lindorm": ("main", 1, ["Lindorm#161"]),
    "LJPH": ("main", 1, ["LJPH#018"]),
    "CeCe": ("main", 1, ["CeCe iwnl#Druss"]),
    "Duke": ("main", 1, ["Duke#padje", "HooD RaT#padje"]),
    "Takaa": ("recurring_sub", 1, ["Takaa#VLT"]),
    "TempoKD": ("recurring_sub", 1, ["TempoKD#Holly"]),
    "Flimsy": ("former_sub", 0, ["Flimsy#212"]),
    "KYCA": ("wel_sub", 0, ["KYCA#KYCA"]),
}
ACCOUNT_OVERRIDES = [
    (re.compile(r"Duke on Takaa's account", re.I), "Takaa#VLT", "Duke"),
    (re.compile(r"TempoKD on Takaa's account", re.I), "Takaa#VLT", "TempoKD"),
]


def slugify(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or hashlib.sha1(text.encode()).hexdigest()[:8]


def clean_note_suffix(name: str) -> str:
    return re.sub(r"\s*\([^)]*(?:account|tracker bug)[^)]*\)\s*$", "", name, flags=re.I).strip()


def parse_event(parts: list[str]) -> tuple[str, str, str]:
    # parts starts after raw games
    root = parts[0]
    if root == "Valorant Premier" and len(parts) >= 2:
        event = f"Valorant Premier · {parts[1]}"
        competition = "Valorant Premier"
        stage_parts = parts[2:-1]
    else:
        event = root
        competition = root.split(" Season ")[0] if " Season " in root else root
        stage_parts = parts[1:-1]
    return event, competition, " / ".join(stage_parts)


def parse_series(path: str) -> dict:
    rel = path.split("raw games/", 1)[1]
    parts = rel.split("/")
    event, competition, stage = parse_event(parts)
    filename = parts[-1][:-5]
    parent = parts[-2] if len(parts) >= 2 else ""

    multi_parent = bool(re.fullmatch(r"G\d+", filename, re.I))
    if multi_parent:
        descriptor = parent
        group_path = "/".join(parts[:-1])
    else:
        descriptor = filename
        group_path = rel[:-5]

    desc_clean = clean_note_suffix(descriptor)
    m = re.search(r"(?:^|\b)vs\s+(.+)$", desc_clean, re.I)
    opponent = m.group(1).strip() if m else desc_clean.strip()
    if opponent.lower().startswith("(impossible to find team name"):
        opponent = "Unknown opponent"

    siblings_hint = multi_parent
    if re.search(r"\bBO3\b", descriptor, re.I) or "Grand Finals vs " in descriptor:
        best_of = 3
    elif re.search(r"\bBO5\b", descriptor, re.I):
        best_of = 5
    else:
        best_of = 1

    map_index = int(filename[1:]) if multi_parent and filename[1:].isdigit() else 1
    return {
        "event": event,
        "competition": competition,
        "stage": stage,
        "series_key": group_path,
        "opponent": opponent,
        "best_of": best_of,
        "map_index": map_index,
    }


def get_value(stats: dict, key: str, default=None):
    v = stats.get(key)
    if isinstance(v, dict):
        return v.get("value", default)
    return default


def canonical_from_account(account: str, path: str, alias_to_player: dict[str, str]) -> str | None:
    for rx, override_account, canonical in ACCOUNT_OVERRIDES:
        if rx.search(path) and account == override_account:
            return canonical
    return alias_to_player.get(account)


def ensure_player(con, name: str, status: str, active: int) -> int:
    slug = slugify(name)
    con.execute(
        "INSERT OR IGNORE INTO players(slug,canonical_name,roster_status,active) VALUES(?,?,?,?)",
        (slug, name, status, active),
    )
    return con.execute("SELECT id FROM players WHERE canonical_name=?", (name,)).fetchone()[0]


def infer_team_id(player_segments, alias_to_player, path):
    counts = Counter()
    for p in player_segments:
        account = p.get("attributes", {}).get("platformUserIdentifier")
        if canonical_from_account(account, path, alias_to_player):
            counts[p.get("metadata", {}).get("teamId")] += 1
    if not counts:
        return None
    # Require a strong signal: at least 3 known W1Z identities on the same side.
    team_id, n = counts.most_common(1)[0]
    return team_id if n >= 3 else None


def round_winner(round_summaries, round_no):
    s = next((x for x in round_summaries if x.get("attributes", {}).get("round") == round_no), None)
    if not s:
        return None
    return get_value(s.get("stats", {}), "winningTeam")


def round_side(segments, round_no, team_id):
    for s in segments:
        if s.get("type") != "player-round":
            continue
        if s.get("attributes", {}).get("round") != round_no:
            continue
        if s.get("metadata", {}).get("teamId") == team_id:
            return s.get("metadata", {}).get("teamSide")
    return None


def pistol_metrics(segments, team_id):
    round_summaries = [s for s in segments if s.get("type") == "round-summary"]
    out = dict(pistol_wins=0, pistol_played=0, attack_wins=0, attack_played=0,
               defense_wins=0, defense_played=0, conversion_wins=0,
               conversion_opportunities=0, first_half_result=None, second_half_result=None)
    for label, pistol_round, next_round in (("first_half_result", 1, 2), ("second_half_result", 13, 14)):
        winner = round_winner(round_summaries, pistol_round)
        if winner is None:
            continue
        side = round_side(segments, pistol_round, team_id)
        won = winner == team_id
        out["pistol_played"] += 1
        out["pistol_wins"] += int(won)
        out[label] = "W" if won else "L"
        if side == "attacker":
            out["attack_played"] += 1
            out["attack_wins"] += int(won)
        elif side == "defender":
            out["defense_played"] += 1
            out["defense_wins"] += int(won)
        if won:
            nxt = round_winner(round_summaries, next_round)
            if nxt is not None:
                out["conversion_opportunities"] += 1
                out["conversion_wins"] += int(nxt == team_id)
    return out


def parse_text_notes(zf):
    notes = []
    for n in zf.namelist():
        if n.endswith("/") or n.lower().endswith(".json"):
            continue
        try:
            body = zf.read(n).decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        notes.append((n, body))
    return notes


def import_all():
    init_db(reset=True)
    issue_count = 0
    imported_maps = 0
    skipped_maps = 0

    with connect() as con, zipfile.ZipFile(SOURCE_ZIP) as zf:
        alias_to_player = {}
        player_ids = {}
        for name, (status, active, aliases) in PLAYER_SEEDS.items():
            pid = ensure_player(con, name, status, active)
            player_ids[name] = pid
            for a in aliases:
                con.execute("INSERT OR IGNORE INTO player_aliases(player_id,riot_id,alias_type) VALUES(?,?,?)", (pid, a, "own_account"))
                alias_to_player[a] = name

        # Audit duplicate raw bytes and match IDs while loading.
        seen_hash = {}
        seen_match = {}
        parsed = []
        for path in sorted(n for n in zf.namelist() if n.lower().endswith(".json")):
            raw = zf.read(path)
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen_hash:
                con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('error','duplicate_file',?,?)",
                            (path, f"Exact duplicate of {seen_hash[digest]}"))
                issue_count += 1
            else:
                seen_hash[digest] = path
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                # Copy/pasting Tracker payloads can append extra JSON/text after a valid first object.
                # Recover the first complete object instead of dropping the map, but make the anomaly visible.
                try:
                    text_raw = raw.decode("utf-8", errors="replace")
                    obj, end = json.JSONDecoder().raw_decode(text_raw)
                    trailing = text_raw[end:].strip()
                    if not trailing:
                        raise e
                    con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('warning','trailing_json_recovered',?,?)",
                                (path, f"Recovered first valid JSON object; ignored {len(trailing)} trailing characters from pasted payload."))
                    issue_count += 1
                except Exception:
                    con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('error','invalid_json',?,?)",
                                (path, str(e)))
                    issue_count += 1
                    skipped_maps += 1
                    continue
            match_id = obj.get("data", {}).get("attributes", {}).get("id")
            if match_id and match_id in seen_match:
                con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('error','duplicate_match_id',?,?)",
                            (path, f"Same match_id as {seen_match[match_id]}"))
                issue_count += 1
            elif match_id:
                seen_match[match_id] = path
            parsed.append((path, raw.decode("utf-8", errors="replace"), obj))

        # Create event notes from text files.
        event_notes = defaultdict(list)
        placement_notes = defaultdict(list)
        bye_notes = []
        for path, body in parse_text_notes(zf):
            rel = path.split("raw games/", 1)[1]
            parts = rel.split("/")
            event, competition, stage = parse_event(parts)
            note = Path(path).stem
            if body:
                note = f"{note}: {body}"
            low = note.lower()
            if "finished" in low:
                placement_notes[event].append(note)
            elif "bye" in low:
                bye_notes.append((event, competition, stage, note, "loss" if "loss" in low else "win"))
            else:
                event_notes[event].append(note)

        # First pass maps grouped as series.
        groups = defaultdict(list)
        for path, raw_text, obj in parsed:
            meta = parse_series(path)
            groups[meta["series_key"]].append((path, raw_text, obj, meta))

        event_ids = {}
        for series_key, items in sorted(groups.items()):
            items.sort(key=lambda x: x[3]["map_index"])
            meta0 = items[0][3]
            event_name = meta0["event"]
            if event_name not in event_ids:
                con.execute("INSERT OR IGNORE INTO events(slug,name,competition,event_notes,placement_text) VALUES(?,?,?,?,?)",
                            (slugify(event_name), event_name, meta0["competition"],
                             "\n".join(event_notes.get(event_name, [])) or None,
                             "\n".join(placement_notes.get(event_name, [])) or None))
                event_ids[event_name] = con.execute("SELECT id FROM events WHERE name=?", (event_name,)).fetchone()[0]

            map_records = []
            series_roster_categories = []
            for path, raw_text, obj, smeta in items:
                data = obj.get("data", {})
                md = data.get("metadata", {})
                segments = data.get("segments", [])
                psummary = [s for s in segments if s.get("type") == "player-summary"]
                team_id = infer_team_id(psummary, alias_to_player, path)
                if not team_id:
                    con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('error','team_unresolved',?,?)",
                                (path, "Could not reliably identify the W1Z side"))
                    issue_count += 1
                    skipped_maps += 1
                    continue

                # Any unknown account on the identified W1Z side becomes an occasional sub.
                roster = []
                actual_by_account = {}
                for p in psummary:
                    if p.get("metadata", {}).get("teamId") != team_id:
                        continue
                    account = p.get("attributes", {}).get("platformUserIdentifier")
                    canonical = canonical_from_account(account, path, alias_to_player)
                    if canonical is None:
                        canonical = account.split("#", 1)[0].strip() or account
                        pid = ensure_player(con, canonical, "occasional_sub", 0)
                        player_ids[canonical] = pid
                        # Alias can be safely attached now: this account appeared on W1Z side.
                        con.execute("INSERT OR IGNORE INTO player_aliases(player_id,riot_id,alias_type,note) VALUES(?,?,?,?)",
                                    (pid, account, "occasional_sub_account", "Discovered on W1Z side during historical import"))
                        alias_to_player[account] = canonical
                    actual_by_account[account] = canonical
                    roster.append(canonical)

                main_missing = [p for p in MAIN_PLAYERS if p not in roster]
                subs_present = [p for p in roster if p not in MAIN_PLAYERS]
                if not subs_present and not main_missing:
                    roster_category = "core"
                elif any(PLAYER_SEEDS.get(p, ("",0,[]))[0] == "wel_sub" for p in subs_present):
                    roster_category = "wel_sub"
                elif any(PLAYER_SEEDS.get(p, ("",0,[]))[0] in ("recurring_sub", "former_sub") for p in subs_present):
                    roster_category = "recurring_sub"
                else:
                    roster_category = "occasional_sub"
                series_roster_categories.append(roster_category)

                team_summary = next((s for s in segments if s.get("type") == "team-summary" and s.get("attributes", {}).get("teamId") == team_id), None)
                opp_summary = next((s for s in segments if s.get("type") == "team-summary" and s.get("attributes", {}).get("teamId") != team_id), None)
                if not team_summary or not opp_summary:
                    con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('error','team_summary_missing',?,?)",
                                (path, "Expected two team-summary segments"))
                    issue_count += 1
                    skipped_maps += 1
                    continue
                sf = int(get_value(team_summary.get("stats", {}), "roundsWon", 0) or 0)
                sa = int(get_value(team_summary.get("stats", {}), "roundsLost", 0) or 0)
                result = "W" if team_summary.get("metadata", {}).get("hasWon") else ("D" if sf == sa else "L")
                quality = "complete"
                stats_complete = 1
                official_rounds = md.get("rounds")
                if "YoruBese" in path:
                    sf, sa, result = 15, 13, "W"
                    quality = "partial"
                    stats_complete = 0
                    official_rounds = 28
                    con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message,resolved) VALUES('warning','partial_tracker_match',?,?,1)",
                                (path, "Tracker stops at 12-12; official result manually fixed to W1Z 15-13. Player stats remain partial."))
                    issue_count += 1

                start_side = round_side(segments, 1, team_id)
                comp_players = []
                for p in psummary:
                    if p.get("metadata", {}).get("teamId") != team_id:
                        continue
                    account = p.get("attributes", {}).get("platformUserIdentifier")
                    canonical = actual_by_account[account]
                    comp_players.append((canonical, p.get("metadata", {}).get("agentName") or "Unknown"))
                comp_key = " / ".join(sorted(agent for _, agent in comp_players))
                map_records.append({
                    "path": path, "raw_text": raw_text, "obj": obj, "meta": smeta, "team_id": team_id,
                    "score_for": sf, "score_against": sa, "result": result, "quality": quality,
                    "stats_complete": stats_complete, "official_rounds": official_rounds,
                    "start_side": start_side, "comp_key": comp_key, "roster": roster,
                    "main_missing": main_missing, "subs_present": subs_present,
                    "actual_by_account": actual_by_account,
                })

            if not map_records:
                continue
            wins = sum(r["result"] == "W" for r in map_records)
            losses = sum(r["result"] == "L" for r in map_records)
            sresult = "W" if wins > losses else ("L" if losses > wins else "D")
            roster_category = "core" if all(x == "core" for x in series_roster_categories) else "with_subs"
            played_at = min(r["obj"]["data"].get("metadata", {}).get("dateStarted") or "9999" for r in map_records)
            con.execute("INSERT INTO series(event_id,series_key,stage,opponent,played_at,best_of,maps_won,maps_lost,result,roster_category) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (event_ids[event_name], series_key, meta0["stage"], meta0["opponent"], played_at,
                         max(meta0["best_of"], len(map_records) if len(map_records) in (3,5) else 1), wins, losses, sresult, roster_category))
            sid = con.execute("SELECT id FROM series WHERE series_key=?", (series_key,)).fetchone()[0]

            for rec in map_records:
                obj = rec["obj"]; data = obj["data"]; md = data.get("metadata", {}); segments = data.get("segments", [])
                if not rec["subs_present"] and not rec["main_missing"]:
                    map_roster_category = "core"
                elif any(PLAYER_SEEDS.get(p, ("",0,[]))[0] == "wel_sub" for p in rec["subs_present"]):
                    map_roster_category = "wel_sub"
                elif any(PLAYER_SEEDS.get(p, ("",0,[]))[0] in ("recurring_sub", "former_sub") for p in rec["subs_present"]):
                    map_roster_category = "recurring_sub"
                else:
                    map_roster_category = "occasional_sub"
                con.execute("""INSERT INTO maps(series_id,match_id,map_index,map_name,map_image_url,played_at,duration_ms,raw_rounds,official_rounds,team_id,start_side,
                            score_for,score_against,result,roster_category,composition_key,data_quality,stats_complete,source_path,raw_json)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (sid, data.get("attributes", {}).get("id"), rec["meta"]["map_index"], md.get("mapName") or "Unknown", md.get("mapImageUrl"),
                             md.get("dateStarted"), md.get("duration"), md.get("rounds"), rec["official_rounds"], rec["team_id"], rec["start_side"],
                             rec["score_for"], rec["score_against"], rec["result"], map_roster_category,
                             rec["comp_key"], rec["quality"], rec["stats_complete"], rec["path"], rec["raw_text"]))
                map_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                imported_maps += 1

                pist = pistol_metrics(segments, rec["team_id"])
                con.execute("""INSERT INTO map_pistols(map_id,pistol_wins,pistol_played,attack_wins,attack_played,defense_wins,defense_played,
                            conversion_wins,conversion_opportunities,first_half_result,second_half_result) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (map_id, pist["pistol_wins"], pist["pistol_played"], pist["attack_wins"], pist["attack_played"],
                             pist["defense_wins"], pist["defense_played"], pist["conversion_wins"], pist["conversion_opportunities"],
                             pist["first_half_result"], pist["second_half_result"]))

                # Team player stats only.
                for p in [x for x in segments if x.get("type") == "player-summary" and x.get("metadata", {}).get("teamId") == rec["team_id"]]:
                    account = p.get("attributes", {}).get("platformUserIdentifier")
                    canonical = rec["actual_by_account"][account]
                    pid = player_ids.get(canonical) or ensure_player(con, canonical, "occasional_sub", 0)
                    player_ids[canonical] = pid
                    st = p.get("stats", {})
                    rank = get_value(st, "rank")
                    tier = (st.get("rank", {}).get("metadata", {}) or {}).get("tierId") if isinstance(st.get("rank"), dict) else None
                    con.execute("""INSERT INTO player_map_stats(map_id,player_id,account_riot_id,agent,agent_image_url,agent_portrait_url,rank,rank_tier_id,kills,deaths,assists,kd,acs,adr,kast,
                                first_kills,first_deaths,damage_delta_per_round,headshot_pct,plants,defuses)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (map_id,pid,account,p.get("metadata",{}).get("agentName"),p.get("metadata",{}).get("agentImageUrl"),p.get("metadata",{}).get("agentPortraitUrl") or p.get("metadata",{}).get("agentImageUrl"),rank,tier,
                                 get_value(st,"kills"),get_value(st,"deaths"),get_value(st,"assists"),get_value(st,"kdRatio"),
                                 get_value(st,"scorePerRound"),get_value(st,"damagePerRound"),get_value(st,"kast") or get_value(st,"kAST"),
                                 get_value(st,"firstKills"),get_value(st,"firstDeaths"),get_value(st,"damageDeltaPerRound"),
                                 get_value(st,"hsAccuracy"),get_value(st,"plants"),get_value(st,"defuses")))

                # Substitution attribution. User-confirmed historical pairings override inference.
                if rec["subs_present"]:
                    if set(rec["subs_present"]) == {"Flimsy", "Takaa"} and set(rec["main_missing"]) == {"LJPH", "CeCe"}:
                        pairs = [("Flimsy", "LJPH"), ("Takaa", "CeCe")]
                        confidence = "exact"
                    else:
                        exact = len(rec["subs_present"]) == len(rec["main_missing"])
                        if exact and len(rec["subs_present"]) == 1:
                            pairs = [(rec["subs_present"][0], rec["main_missing"][0])]
                            confidence = "exact"
                        else:
                            pairs = [(sub, None) for sub in rec["subs_present"]]
                            confidence = "ambiguous"
                    for sub, replaced in pairs:
                        con.execute("INSERT INTO substitutions(map_id,sub_player_id,replaced_player_id,confidence,note) VALUES(?,?,?,?,?)",
                                    (map_id, player_ids[sub], player_ids.get(replaced) if replaced else None, confidence,
                                     None if confidence == "exact" else f"Missing main players: {', '.join(rec['main_missing'])}"))
                    if confidence == "ambiguous":
                        con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('info','ambiguous_substitution',?,?)",
                                    (rec["path"], f"Subs present {rec['subs_present']}; missing mains {rec['main_missing']}. Pairing intentionally not guessed."))
                        issue_count += 1

                # Expected structural exception: Lost Puppies G1 opponent chose to play 4v5.
                pcount = len([x for x in segments if x.get("type") == "player-summary"])
                if pcount != 10:
                    if "Lost Puppies/G1.json" in rec["path"] and pcount == 9:
                        con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message,resolved) VALUES('info','expected_4v5',?,?,1)",
                                    (rec["path"], "9 player summaries is expected: Lost Puppies intentionally played G1 as 4v5."))
                    else:
                        con.execute("INSERT INTO data_issues(severity,issue_type,source_path,message) VALUES('warning','unexpected_player_count',?,?)",
                                    (rec["path"], f"Found {pcount} player-summary segments"))
                        issue_count += 1

        # Add bye/forfeit path entries as series with no maps. Excluded from performance WR by is_bye=1.
        for event_name, competition, stage, note, outcome in bye_notes:
            if event_name not in event_ids:
                con.execute("INSERT OR IGNORE INTO events(slug,name,competition,event_notes,placement_text) VALUES(?,?,?,?,?)",
                            (slugify(event_name), event_name, competition, None, "\n".join(placement_notes.get(event_name, [])) or None))
                event_ids[event_name] = con.execute("SELECT id FROM events WHERE name=?", (event_name,)).fetchone()[0]
            key = f"bye::{event_name}::{stage}::{note}"
            con.execute("INSERT INTO series(event_id,series_key,stage,opponent,best_of,maps_won,maps_lost,result,roster_category,is_bye,bye_result,notes) VALUES(?,?,?,?,1,0,0,'N/A','N/A',1,?,?)",
                        (event_ids[event_name], key, stage, "BYE / FORFEIT", outcome.upper(), note))

        # Event date ranges.
        con.execute("""UPDATE events SET first_date=(SELECT MIN(s.played_at) FROM series s WHERE s.event_id=events.id AND s.played_at IS NOT NULL),
                                      last_date=(SELECT MAX(s.played_at) FROM series s WHERE s.event_id=events.id AND s.played_at IS NOT NULL)""")

        # Data health: duplicate heuristic on date/map/roster/score among imported maps.
        dupes = con.execute("""SELECT played_at,map_name,score_for,score_against,COUNT(*) c,GROUP_CONCAT(source_path,' || ') paths
                              FROM maps GROUP BY played_at,map_name,score_for,score_against HAVING c>1""").fetchall()
        for d in dupes:
            con.execute("INSERT INTO data_issues(severity,issue_type,message) VALUES('warning','heuristic_duplicate',?)",
                        (f"Potential duplicate signature: {d['paths']}",))
            issue_count += 1

    print(json.dumps({"database": str(DB_PATH), "maps_imported": imported_maps, "maps_skipped": skipped_maps, "issues_logged": issue_count}, indent=2))

if __name__ == "__main__":
    import_all()
