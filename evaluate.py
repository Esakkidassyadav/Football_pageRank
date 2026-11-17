"""
evaluate.py - STEP 3: does PageRank agree with the official Player of the Match?

There is no "correct answer" for who is the most influential player, so we
compare with the closest thing we have: the official Player of the Match.
  * FIFA World Cup 2022: chosen by a fan vote on the FIFA+ website.
  * UEFA Euro 2024: chosen by UEFA's technical observers (experienced coaches).

For every match we rank the award winner's team by five methods and check
where the award winner lands:
  1. PageRank                        (this project)
  2. Passes received                 (simple count: how often he got the ball)
  3. Passes made                     (simple count: how often he passed)
  4. Goals + assists                 (ties broken by expected goals, xG)
  5. Goals + assists, then PageRank  (ties broken by PageRank instead)
and we also show what picking a player at random would give.

The award winners are compared with the network of the WHOLE match, because
many of them were substitutes or were substituted.

Scores we report
  Top-1 hit   the award winner was the method's No. 1 player in his team
  Top-3 hit   the award winner was in the method's top 3 of his team
  Avg rank    his average position in the method's list (1 = best)

Run:   python evaluate.py
"""
import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

import config
from pagerank_engine import build_network, pagerank_networkx

# method name -> columns to sort by (the 2nd and 3rd columns only break ties)
METHODS = {
    "PageRank": ["pagerank"],
    "Passes received": ["passes_received", "pagerank"],
    "Passes made": ["passes_made", "pagerank"],
    "Goals + assists": ["goal_involvement", "xg", "pagerank"],
    "Goals + assists, then PageRank": ["goal_involvement", "pagerank"],
}


# ----------------------------------------------------------------------
# Matching the award winner's name to the StatsBomb name
# ----------------------------------------------------------------------
def normalise(name):
    """'Alexis Mac Allister' and 'Alexis MacAllister' -> comparable lowercase words."""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ı", "i").replace("ł", "l").replace("ø", "o").replace("đ", "d")
    text = re.sub(r"[-'’.]", " ", text.lower())
    return " ".join(text.split())


def name_score(award_name, player_row):
    """1.0 = certain match. StatsBomb often uses full legal names (e.g. 'Gavi' is 'Pablo Martín Páez Gavira')."""
    a = normalise(award_name)
    best = 0.0
    for candidate in (player_row["player"], player_row["full_name"]):
        c = normalise(candidate)
        if a == c or a.replace(" ", "") == c.replace(" ", ""):
            return 1.0
        if set(a.split()) <= set(c.split()):
            best = max(best, 0.95)
        best = max(best, SequenceMatcher(None, a.replace(" ", ""), c.replace(" ", "")).ratio() * 0.9)
    return best


def find_match(potm_row, matches):
    """The StatsBomb match for one award row: same two teams, date within a day."""
    pair = {potm_row["team_a"], potm_row["team_b"]}
    day = pd.Timestamp(potm_row["date"])
    m = matches[(matches["competition"] == potm_row["competition"])]
    m = m[m.apply(lambda r: {r["home_team"], r["away_team"]} == pair, axis=1)]
    m = m[(pd.to_datetime(m["date"]) - day).abs() <= pd.Timedelta(days=1)]
    return m.iloc[0] if len(m) else None


# ----------------------------------------------------------------------
# The evaluation
# ----------------------------------------------------------------------
def rank_team(nodes):
    """Add one rank column per method (1 = top of the team)."""
    nodes = nodes.copy()
    nodes["goal_involvement"] = nodes["goals"] + nodes["assists"]
    for method, cols in METHODS.items():
        order = nodes.sort_values(cols, ascending=False).index
        nodes.loc[order, f"rank_{method}"] = np.arange(1, len(nodes) + 1)
    return nodes


def evaluate(passes, players, matches, potm, window="full", include_set_pieces=True):
    """
    Returns
      per_match  one row per award: who won it, and where each method ranked him
      summary    hit rates per method (all matches, and split by tournament)
      problems   award rows that could not be matched to the data
    """
    rows, problems = [], []
    for _, award in potm.iterrows():
        match = find_match(award, matches)
        if match is None:
            problems.append(f"{award['competition']} {award['date']} {award['team_a']} v {award['team_b']}: match not found")
            continue
        net = build_network(passes, players, match["match_id"], award["potm_team"], window, include_set_pieces)
        nodes = rank_team(net["nodes"])
        scores = nodes.apply(lambda r: name_score(award["player_of_the_match"], r), axis=1)
        if scores.empty or scores.max() < 0.75:
            problems.append(f"{award['competition']} {award['date']}: '{award['player_of_the_match']}' "
                            f"not found in {award['potm_team']}'s players")
            continue
        winner = nodes.loc[scores.idxmax()]
        n = len(nodes)
        row = {
            "competition": award["competition"],
            "chosen_by": award["chosen_by"],
            "date": match["date"],
            "stage": match["stage"],
            "match": f"{match['home_team']} {match['home_score']}-{match['away_score']} {match['away_team']}",
            "match_id": match["match_id"],
            "player_of_the_match": award["player_of_the_match"],
            "team": award["potm_team"],
            "statsbomb_name": winner["full_name"],
            "name_match_score": round(float(scores.max()), 2),
            "position_group": winner["position_group"],
            "goals": int(winner["goals"]),
            "assists": int(winner["assists"]),
            "scored_or_assisted": bool(winner["goals"] + winner["assists"] > 0),
            "team_players": n,
            "pagerank_share": float(winner["pagerank"]),
            "team_top_pagerank_player": nodes.sort_values("pagerank", ascending=False)["player"].iloc[0],
        }
        for method in METHODS:
            row[f"rank_{method}"] = int(winner[f"rank_{method}"])
        rows.append(row)

    per_match = pd.DataFrame(rows)
    return per_match, summarise(per_match), problems


def summarise(per_match):
    """Top-1 / top-3 hit rates and average rank, for every method and for random picks."""
    if per_match.empty:
        return pd.DataFrame()
    groups = [("All matches", per_match)]
    for comp, g in per_match.groupby("competition"):
        groups.append((comp, g))
    groups.append(("Winner did not score or assist", per_match[~per_match["scored_or_assisted"]]))
    groups.append(("Winner was not a goalkeeper", per_match[per_match["position_group"] != "Goalkeeper"]))

    out = []
    for name, g in groups:
        if g.empty:
            continue
        n_team = g["team_players"]
        out.append({"group": name, "method": "Random pick", "awards": len(g),
                    "top1_pct": float((1 / n_team).mean() * 100),
                    "top3_pct": float((np.minimum(3, n_team) / n_team).mean() * 100),
                    "avg_rank": float(((n_team + 1) / 2).mean())})
        for method in METHODS:
            r = g[f"rank_{method}"]
            out.append({"group": name, "method": method, "awards": len(g),
                        "top1_pct": float((r == 1).mean() * 100),
                        "top3_pct": float((r <= 3).mean() * 100),
                        "avg_rank": float(r.mean())})
    return pd.DataFrame(out)


def check_pagerank_code(passes, players, matches):
    """
    Compare our hand-written PageRank with the networkx library on every team in every match.
    Returns the number of networks checked and the biggest difference found.
    """
    biggest, checked = 0.0, 0
    for m in matches.itertuples():
        for team in (m.home_team, m.away_team):
            net = build_network(passes, players, m.match_id, team)
            ours = net["nodes"].set_index("player_id").loc[net["ids"], "pagerank"].values
            theirs = pagerank_networkx(net["W"])
            biggest = max(biggest, float(np.abs(ours - theirs).max()))
            checked += 1
    return checked, biggest


def load_all():
    matches = pd.read_csv(config.MATCHES_FILE)
    players = pd.read_csv(config.PLAYERS_FILE)
    passes = pd.read_csv(config.PASSES_FILE)
    potm = pd.read_csv(config.POTM_FILE)
    return matches, players, passes, potm


def main():
    matches, players, passes, potm = load_all()
    per_match, summary, problems = evaluate(passes, players, matches, potm)
    print(f"Awards checked: {len(per_match)} of {len(potm)}")
    for p in problems:
        print("  ! " + p)
    unsure = per_match[per_match["name_match_score"] < 1.0]
    if len(unsure):
        print("\nNames matched by similarity (check these):")
        print(unsure[["player_of_the_match", "statsbomb_name", "name_match_score"]].to_string(index=False))
    for group, g in summary.groupby("group", sort=False):
        print(f"\n{group} ({int(g['awards'].iloc[0])} awards)")
        print(f"  {'Method':32s} {'Top-1 hit':>10s} {'Top-3 hit':>10s} {'Avg rank':>9s}")
        for r in g.itertuples():
            print(f"  {r.method:32s} {r.top1_pct:9.0f}% {r.top3_pct:9.0f}% {r.avg_rank:9.1f}")

    print("\nChecking our PageRank code against the networkx library...")
    checked, biggest = check_pagerank_code(passes, players, matches)
    print(f"  {checked} team networks checked. Biggest difference: {biggest:.1e} (0 = identical)")


if __name__ == "__main__":
    main()
