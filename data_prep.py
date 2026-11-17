"""
data_prep.py - STEP 1: download the football data and turn it into small tables.

Data source: StatsBomb Open Data (https://github.com/statsbomb/open-data).
StatsBomb record every action of a match (passes, shots, tackles...) with the
player, the time and the place on the pitch. They give some tournaments away
free for learning and research.

What this script does
  1. Downloads the match list, the events and the line-ups of every match
     in config.COMPETITIONS (raw JSON files, kept in data/raw/).
  2. Keeps only what the project needs and saves three tables in data/:
       matches.csv     one row per match (teams, score, date, stage)
       players.csv     one row per player per match (minutes, goals, passes...)
       passes.csv.gz   every completed pass: who passed, who received, where

Run:   python data_prep.py            build everything (downloads ~650 MB the first time)
       python data_prep.py --list     show every free StatsBomb competition
       python data_prep.py --raw-dir D:/statsbomb/data   use JSON files you already have

You do NOT need to run this for the project to work: the three tables are
already in the data folder. Run it only to rebuild them or to add a tournament.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

import config


def log(message):
    print(message, flush=True)


# ----------------------------------------------------------------------
# Downloading (with a local copy, so nothing is downloaded twice)
# ----------------------------------------------------------------------
def get_json(relative_path, raw_dir, tries=3):
    """Read data/raw/<relative_path>, downloading it from StatsBomb's GitHub first if missing."""
    local = Path(raw_dir) / relative_path
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    url = f"{config.STATSBOMB_URL}/{relative_path}"
    error = None
    for attempt in range(tries):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(json.dumps(data), encoding="utf-8")
            return data
        except (requests.RequestException, ValueError) as exc:
            error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {error}")


def list_competitions(raw_dir):
    comps = get_json("competitions.json", raw_dir)
    rows = [{"competition_id": c["competition_id"], "season_id": c["season_id"],
             "competition": c["competition_name"], "season": c["season_name"],
             "gender": c["competition_gender"]} for c in comps]
    return pd.DataFrame(rows).sort_values(["competition", "season"])


# ----------------------------------------------------------------------
# Small helpers for the StatsBomb format
# ----------------------------------------------------------------------
def clock_to_minutes(text):
    """'64:10' -> 64.17 (match clock: minutes:seconds)."""
    if not text:
        return None
    mins, secs = text.split(":")
    return int(mins) + int(secs) / 60


def event_minute(e):
    return e["minute"] + e["second"] / 60


def position_group(position_name):
    """Turn StatsBomb's 25 positions into 4 simple groups."""
    p = (position_name or "").lower()
    if "goalkeeper" in p:
        return "Goalkeeper"
    if "back" in p:
        return "Defender"
    if "forward" in p or "striker" in p or "wing" in p:
        return "Forward"
    if "midfield" in p:
        return "Midfielder"
    return "Unknown"


def team_name(team_id, name):
    """One name per club for the whole season (see TEAM_NAME_FIXES in config.py)."""
    return config.TEAM_NAME_FIXES.get(team_id, name)


def stage_order(stage):
    order = {"Group Stage": 1, "Regular Season": 1, "Round of 16": 2, "Quarter-finals": 3,
             "Semi-finals": 4, "Play-offs - Semi-Finals": 4, "3rd Place Final": 5, "Final": 6,
             "Championship - Final": 6}
    return order.get(stage, 1)


# ----------------------------------------------------------------------
# Turning one match into table rows
# ----------------------------------------------------------------------
def process_match(match, events, lineups, competition_label):
    match_id = match["match_id"]
    home = team_name(match["home_team"]["home_team_id"], match["home_team"]["home_team_name"])
    away = team_name(match["away_team"]["away_team_id"], match["away_team"]["away_team_name"])

    # Ignore the penalty shoot-out (period 5): it is not open play
    events = [e for e in events if e.get("period", 1) <= 4]
    end_minute = max((event_minute(e) for e in events), default=90.0)

    # ---- players: minutes from the line-ups ----
    players = {}
    for team in lineups:
        for p in team["lineup"]:
            spells = p.get("positions") or []
            if not spells:
                continue                       # on the bench, never came on
            on = clock_to_minutes(spells[0]["from"]) or 0.0
            last_to = spells[-1]["to"]
            off = clock_to_minutes(last_to) if last_to else end_minute
            off = min(off, end_minute)
            # the position he spent the most time in
            longest, best = -1.0, spells[0]["position"]
            for s in spells:
                s_from = clock_to_minutes(s["from"]) or 0.0
                s_to = clock_to_minutes(s["to"]) if s["to"] else end_minute
                if s_to - s_from > longest:
                    longest, best = s_to - s_from, s["position"]
            players[p["player_id"]] = {
                "match_id": match_id,
                "team": team_name(team["team_id"], team["team_name"]),
                "player_id": p["player_id"],
                "player": p.get("player_nickname") or p["player_name"],
                "full_name": p["player_name"],
                "jersey": p.get("jersey_number"),
                "position": best,
                "position_group": position_group(best),
                "started": spells[0].get("start_reason") == "Starting XI",
                "minute_on": round(on, 2),
                "minute_off": round(off, 2),
                "minutes": round(max(off - on, 0.0), 1),
                "red_card": any("Red" in (c.get("card_type") or "") for c in p.get("cards") or []),
                "passes_attempted": 0, "passes_completed": 0, "passes_received": 0,
                "goals": 0, "assists": 0, "key_passes": 0, "shots": 0, "xg": 0.0,
            }

    # ---- passes and per-player numbers from the events ----
    pass_rows = []
    for e in events:
        kind = e["type"]["name"]
        pid = e.get("player", {}).get("id")
        stats = players.get(pid)
        if kind == "Pass":
            info = e["pass"]
            if stats:
                stats["passes_attempted"] += 1
                if info.get("goal_assist"):
                    stats["assists"] += 1
                if info.get("goal_assist") or info.get("shot_assist"):
                    stats["key_passes"] += 1
            completed = "outcome" not in info          # StatsBomb leaves 'outcome' out when the pass arrived
            recipient = info.get("recipient", {}).get("id")
            if completed and recipient is not None:
                if stats:
                    stats["passes_completed"] += 1
                if recipient in players:
                    players[recipient]["passes_received"] += 1
                start = e.get("location") or [None, None]
                end = info.get("end_location") or [None, None]
                pass_rows.append({
                    "match_id": match_id,
                    "team": team_name(e["team"]["id"], e["team"]["name"]),
                    "period": e["period"],
                    "minute": round(event_minute(e), 2),
                    "passer_id": pid,
                    "recipient_id": recipient,
                    "x": start[0], "y": start[1],
                    "end_x": end[0], "end_y": end[1],
                    "set_piece": info.get("type", {}).get("name") in config.SET_PIECES,
                })
        elif kind == "Shot" and stats:
            stats["shots"] += 1
            stats["xg"] += e["shot"].get("statsbomb_xg", 0.0) or 0.0
            if e["shot"].get("outcome", {}).get("name") == "Goal":
                stats["goals"] += 1

    for s in players.values():
        s["xg"] = round(s["xg"], 3)

    stage = match.get("competition_stage", {}).get("name", "")
    match_row = {
        "match_id": match_id,
        "competition": competition_label,
        "date": match["match_date"],
        "kick_off": (match.get("kick_off") or "")[:5],
        "stage": stage,
        "stage_order": stage_order(stage),
        "match_week": match.get("match_week"),
        "home_team": home,
        "away_team": away,
        "home_score": match.get("home_score"),
        "away_score": match.get("away_score"),
        "stadium": (match.get("stadium") or {}).get("name", ""),
        "completed_passes": len(pass_rows),
    }
    return match_row, list(players.values()), pass_rows


# ----------------------------------------------------------------------
# Everything together
# ----------------------------------------------------------------------
def build(raw_dir=config.RAW_DIR, competitions=config.COMPETITIONS, workers=8):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_matches, all_players, all_passes, summary = [], [], [], []

    for comp in competitions:
        cid, sid, label = comp["competition_id"], comp["season_id"], comp["label"]
        matches = get_json(f"matches/{cid}/{sid}.json", raw_dir)
        log(f"{label}: {len(matches)} matches. Getting events and line-ups...")

        def load(m):
            mid = m["match_id"]
            return m, get_json(f"events/{mid}.json", raw_dir), get_json(f"lineups/{mid}.json", raw_dir)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (m, events, lineups) in enumerate(pool.map(load, matches), start=1):
                match_row, player_rows, pass_rows = process_match(m, events, lineups, label)
                all_matches.append(match_row)
                all_players.extend(player_rows)
                all_passes.extend(pass_rows)
                if i % 20 == 0 or i == len(matches):
                    log(f"   {i}/{len(matches)} matches done")
        summary.append({"competition": label, "competition_id": cid, "season_id": sid,
                        "matches": len(matches)})

    matches_df = pd.DataFrame(all_matches).sort_values(["competition", "date", "kick_off"])
    players_df = pd.DataFrame(all_players)
    passes_df = pd.DataFrame(all_passes)

    matches_df.to_csv(config.MATCHES_FILE, index=False, encoding="utf-8")
    players_df.to_csv(config.PLAYERS_FILE, index=False, encoding="utf-8")
    passes_df.to_csv(config.PASSES_FILE, index=False, encoding="utf-8", compression="gzip")

    info = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "StatsBomb Open Data - https://github.com/statsbomb/open-data",
        "competitions": summary,
        "matches": int(len(matches_df)),
        "player_rows": int(len(players_df)),
        "completed_passes": int(len(passes_df)),
    }
    config.DATA_INFO_FILE.write_text(json.dumps(info, indent=2), encoding="utf-8")
    log(f"\nSaved {len(matches_df)} matches, {len(players_df)} player rows and "
        f"{len(passes_df):,} completed passes in {config.DATA_DIR}")
    return info


def main():
    parser = argparse.ArgumentParser(description="Download StatsBomb Open Data and build the project tables.")
    parser.add_argument("--list", action="store_true", help="show every free StatsBomb competition and stop")
    parser.add_argument("--raw-dir", default=str(config.RAW_DIR),
                        help="folder with StatsBomb JSON files (default: data/raw, downloaded if missing)")
    args = parser.parse_args()

    if args.list:
        with pd.option_context("display.max_rows", 200, "display.width", 120):
            print(list_competitions(args.raw_dir).to_string(index=False))
        print("\nTo add one, put its competition_id and season_id in COMPETITIONS in config.py.")
        return
    try:
        build(raw_dir=args.raw_dir)
    except KeyboardInterrupt:
        log("\nStopped. Run the same command again: files already downloaded are kept.")
        sys.exit(1)
    log("Done. Now start the website with:  python app.py")


if __name__ == "__main__":
    main()
