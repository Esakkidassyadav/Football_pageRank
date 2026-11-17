"""
pagerank_engine.py - STEP 2: build a passing network and rank the players with PageRank.

The idea in one line: a pass is a link. Google's PageRank says a web page is
important when important pages link to it. Here a player is important when
the ball keeps reaching him from players who also get the ball a lot.

How the network is built (for one team in one match)
  * Node  = a player.
  * Edge  = passes from player A to player B. Its weight = how many completed
            passes went from A to B. Edges have a direction (A->B is not B->A).

How PageRank works (power iteration, written out by hand below)
  1. Every player starts with the same score: 1 / n.
  2. In each round, every player hands his score to his team-mates, split in
     proportion to how many passes he gave each of them.
  3. With probability (1 - d) the ball "jumps" to a random player instead
     (d = damping factor = 0.85, the value Google used). This keeps the scores
     from getting stuck, e.g. on a player who never passes.
  4. Repeat until the scores stop changing. The scores always add up to 1,
     so a score of 0.15 means "15% of the team's ball flow ends up with him".

Formula for player j in each round:
    PR(j) = (1 - d) / n  +  d * sum over i of  PR(i) * passes(i -> j) / all_passes_made_by(i)
"""
import networkx as nx
import numpy as np
import pandas as pd

import config


# ----------------------------------------------------------------------
# PageRank by hand (power iteration)
# ----------------------------------------------------------------------
def transition_matrix(W):
    """
    Turn pass counts into "where does the ball go next" chances.
    Row i of the result = the share of player i's passes that went to each team-mate.
    A player with no completed passes (rare: e.g. a sub who came on at the end)
    is treated as passing to everybody equally, which is the standard fix.
    """
    W = np.asarray(W, dtype=float)
    n = W.shape[0]
    row_sums = W.sum(axis=1, keepdims=True)
    P = np.divide(W, row_sums, out=np.full_like(W, 1.0 / n), where=row_sums > 0)
    return P


def pagerank(W, damping=config.DAMPING, tol=config.TOLERANCE, max_rounds=config.MAX_ROUNDS,
             keep_history=False):
    """
    PageRank of every node of a weighted, directed network.

    W[i, j] = number of passes from player i to player j.
    Returns (scores, rounds_used, history). The scores add up to 1.
    `history` is the list of score vectors after every round (for the app's demo).
    """
    W = np.asarray(W, dtype=float)
    n = W.shape[0]
    if n == 0:
        return np.array([]), 0, []
    P = transition_matrix(W)
    r = np.full(n, 1.0 / n)                     # step 1: everyone starts equal
    history = [r.copy()] if keep_history else []
    for rounds in range(1, max_rounds + 1):
        r_new = (1 - damping) / n + damping * (r @ P)   # steps 2-3
        if keep_history:
            history.append(r_new.copy())
        if np.abs(r_new - r).sum() < tol:       # step 4: stop when nothing changes
            return r_new / r_new.sum(), rounds, history
        r = r_new
    return r / r.sum(), max_rounds, history


def pagerank_networkx(W, damping=config.DAMPING):
    """The same thing with the networkx library, used only to check our own code."""
    G = nx.DiGraph()
    n = len(W)
    G.add_nodes_from(range(n))
    for i in range(n):
        for j in range(n):
            if W[i][j] > 0:
                G.add_edge(i, j, weight=float(W[i][j]))
    pr = nx.pagerank(G, alpha=damping, weight="weight", tol=1e-12, max_iter=1000)
    return np.array([pr[i] for i in range(n)])


# ----------------------------------------------------------------------
# Building the network of one team in one match
# ----------------------------------------------------------------------
def first_substitution_minute(players, match_id, team):
    """Minute when the team made its first change (or lost a player to a red card)."""
    squad = players[(players["match_id"] == match_id) & (players["team"] == team)]
    subs_on = squad.loc[~squad["started"], "minute_on"]
    sent_off = squad.loc[squad["started"] & squad["red_card"], "minute_off"]
    candidates = pd.concat([subs_on, sent_off])
    return float(candidates.min()) if len(candidates) else None


def build_network(passes, players, match_id, team, window="full", include_set_pieces=True,
                  with_betweenness=True):
    """
    Make the passing network of one team in one match.

    window = "full"       every player who played, the whole match
             "first_sub"  only the starting XI, until the team's first substitution
                          (the usual way analysts draw a passing network, because
                          everyone on it was on the pitch at the same time)

    Returns a dict with:
      nodes   one row per player: average position, passes, PageRank, rank...
      edges   one row per (passer, receiver) pair with the number of passes
      W       the pass-count matrix used for PageRank
      info    team-level numbers (passes, time window, rounds PageRank needed)
    """
    squad = players[(players["match_id"] == match_id) & (players["team"] == team)].copy()
    p = passes[(passes["match_id"] == match_id) & (passes["team"] == team)]
    if not include_set_pieces:
        p = p[~p["set_piece"]]

    cut = None
    if window == "first_sub":
        cut = first_substitution_minute(players, match_id, team)
        squad = squad[squad["started"]]
        if cut is not None:
            p = p[p["minute"] < cut]

    ids = squad["player_id"].tolist()
    index = {pid: k for k, pid in enumerate(ids)}
    p = p[p["passer_id"].isin(index) & p["recipient_id"].isin(index)]

    n = len(ids)
    W = np.zeros((n, n))
    pair_counts = p.groupby(["passer_id", "recipient_id"]).size()
    for (a, b), c in pair_counts.items():
        W[index[a], index[b]] = c

    scores, rounds, _ = pagerank(W)

    # average position = mean of where he passed from and where he received the ball
    made = p[["passer_id", "x", "y"]].rename(columns={"passer_id": "player_id"})
    got = p[["recipient_id", "end_x", "end_y"]].rename(
        columns={"recipient_id": "player_id", "end_x": "x", "end_y": "y"})
    spots = pd.concat([made, got]).groupby("player_id")[["x", "y"]].mean()

    nodes = squad.set_index("player_id").loc[ids, ["player", "full_name", "jersey", "position",
                                                    "position_group", "started", "minutes",
                                                    "goals", "assists", "xg"]].copy()
    # minutes this player spent inside the time window of this network
    sq = squad.set_index("player_id").loc[ids]
    window_end = sq["minute_off"] if cut is None else np.minimum(sq["minute_off"], cut)
    nodes["minutes_in_network"] = np.clip(window_end - sq["minute_on"], 0, None).round(0)
    nodes["passes_made"] = W.sum(axis=1).astype(int)
    nodes["passes_received"] = W.sum(axis=0).astype(int)
    nodes["team_mates_passed_to"] = (W > 0).sum(axis=1)
    nodes["pagerank"] = scores
    nodes["vs_average"] = scores * n                # 1.0 = exactly the team average
    nodes["avg_x"] = spots["x"].reindex(ids).values
    nodes["avg_y"] = spots["y"].reindex(ids).values
    nodes["betweenness"] = betweenness(W) if with_betweenness else np.nan
    nodes = nodes.reset_index()
    nodes["rank"] = nodes["pagerank"].rank(ascending=False, method="min").astype(int)
    nodes = nodes.sort_values("pagerank", ascending=False).reset_index(drop=True)

    edges = pair_counts.rename("passes").reset_index()
    names = squad.set_index("player_id")["player"]
    edges["passer"] = edges["passer_id"].map(names)
    edges["recipient"] = edges["recipient_id"].map(names)

    info = {
        "match_id": match_id, "team": team, "window": window,
        "until_minute": cut, "players": n, "passes": int(W.sum()),
        "pagerank_rounds": rounds,
        "links_used": int((W > 0).sum()),
        "possible_links": n * (n - 1),
        "top_share": float(scores.max()) if n else 0.0,
        "top3_share": float(np.sort(scores)[::-1][:3].sum()) if n else 0.0,
    }
    return {"nodes": nodes, "edges": edges, "W": W, "ids": ids, "info": info}


def betweenness(W):
    """
    Betweenness: how often a player sits on the shortest route between two team-mates.
    A pair that passes a lot is 'close', so distance = 1 / passes.
    """
    n = len(W)
    if n < 3:
        return np.zeros(n)
    G = nx.DiGraph()
    G.add_nodes_from(range(n))
    for i in range(n):
        for j in range(n):
            if W[i][j] > 0:
                G.add_edge(i, j, distance=1.0 / W[i][j])
    b = nx.betweenness_centrality(G, weight="distance", normalized=True)
    return np.array([b[i] for i in range(n)])


# ----------------------------------------------------------------------
# Every team in every match (for the leaderboard and the evaluation)
# ----------------------------------------------------------------------
def all_networks(passes, players, matches, window="full", include_set_pieces=True):
    """PageRank of every player in every match. One row per player per match."""
    rows = []
    passes_by_match = dict(tuple(passes.groupby("match_id")))
    players_by_match = dict(tuple(players.groupby("match_id")))
    for m in matches.itertuples():
        p_match = passes_by_match.get(m.match_id, passes.iloc[0:0])
        pl_match = players_by_match.get(m.match_id, players.iloc[0:0])
        for team in (m.home_team, m.away_team):
            net = build_network(p_match, pl_match, m.match_id, team, window, include_set_pieces,
                                with_betweenness=False)
            nd = net["nodes"].copy()
            nd["match_id"] = m.match_id
            nd["team"] = team
            nd["opponent"] = m.away_team if team == m.home_team else m.home_team
            nd["competition"] = m.competition
            nd["team_size"] = len(nd)
            rows.append(nd)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
