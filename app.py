"""
app.py - STEP 4: the website (a small web server that runs on your laptop).

Run:   python app.py
Then open http://localhost:5000 in your browser.

The website is built with Flask (a small Python web framework):
  * this file answers the browser's requests with data (as JSON)
  * templates/index.html is the page, static/app.js fills it in and draws
    the charts with Plotly, static/style.css is the look

Tabs
  Pass network          one team's passing network on a pitch, and its PageRank table
  Team vs team          both teams side by side
  Tournament leaders    the players a team "ran through" most often across a tournament
  Player of the Match   does PageRank agree with the official award? (the evaluation)
  How PageRank works    the algorithm step by step on the chosen team
  About the data        where the data comes from and how it was prepared
"""
import json
import math
import threading
import webbrowser
from collections import defaultdict

import numpy as np
import pandas as pd
from flask import Flask, Response, jsonify, render_template, request
from plotly.offline import get_plotlyjs
from scipy.stats import spearmanr

import charts
import config
import evaluate
import pagerank_engine as pe

app = Flask(__name__)
app.json.sort_keys = False

WINDOWS = {"first_sub": "Starting XI until the first substitution", "full": "Whole match (all players)"}
POSITIONS = ["All", "Goalkeeper", "Defender", "Midfielder", "Forward"]
EVAL_GROUPS = ["All matches", "FIFA World Cup 2022", "UEFA Euro 2024", "Winner did not score or assist"]
METHOD_ORDER = ["Random pick", "Passes made", "Passes received", "PageRank", "Goals + assists",
                "Goals + assists, then PageRank"]


# ----------------------------------------------------------------------
# Data (read once when the website starts)
# ----------------------------------------------------------------------
def load_data():
    missing = [f.name for f in (config.MATCHES_FILE, config.PLAYERS_FILE, config.PASSES_FILE) if not f.exists()]
    if missing:
        raise SystemExit("These data files are missing: " + ", ".join(missing)
                         + "\nMake them with:  python data_prep.py   (needs internet the first time)")
    matches = pd.read_csv(config.MATCHES_FILE)
    players = pd.read_csv(config.PLAYERS_FILE)
    passes = pd.read_csv(config.PASSES_FILE)
    potm = pd.read_csv(config.POTM_FILE) if config.POTM_FILE.exists() else pd.DataFrame()
    info = json.loads(config.DATA_INFO_FILE.read_text(encoding="utf-8")) if config.DATA_INFO_FILE.exists() else {}
    return matches, players, passes, potm, info


print("Reading the data ...", flush=True)
MATCHES, PLAYERS, PASSES, POTM, DATA_INFO = load_data()
MATCH_BY_ID = MATCHES.set_index("match_id")
PASSES_BY_MATCH = dict(tuple(PASSES.groupby("match_id")))
PLAYERS_BY_MATCH = dict(tuple(PLAYERS.groupby("match_id")))
TOURNAMENTS = list(dict.fromkeys(MATCHES["competition"]))

_cache = {}
_locks = defaultdict(threading.Lock)      # one lock per table, so one slow table never blocks another


def remembered(key, make):
    """Work a table out once, then keep it for as long as the website runs."""
    with _locks[key]:
        if key not in _cache:
            _cache[key] = make()
        return _cache[key]


def all_networks(window, set_pieces):
    """PageRank of every player in every match (a few seconds the first time, then remembered)."""
    return remembered(("all", window, set_pieces),
                      lambda: pe.all_networks(PASSES, PLAYERS, MATCHES, window=window, include_set_pieces=set_pieces))


def evaluation():
    return remembered("evaluation", lambda: evaluate.evaluate(PASSES, PLAYERS, MATCHES, POTM, window="full"))


def get_network(match_id, team, window, set_pieces):
    return pe.build_network(PASSES_BY_MATCH[match_id], PLAYERS_BY_MATCH[match_id], match_id, team,
                            window=window, include_set_pieces=set_pieces)


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def clean(value):
    """Make a value safe to send as JSON: NaN becomes null, numpy numbers become Python numbers."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) or math.isinf(value) else float(value)
    return value


def fmt(x, spec):
    if x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x):
        return "-"
    if spec == "%":
        return f"{x:.1%}"
    return format(x, spec)


def make_table(frame, columns, bar=None):
    """
    A table for the browser. `columns` is a list of (column_in_frame, title, number_format);
    a format of None means text. `bar` names a column that also gets a small bar in its cell.
    """
    rows = [[str(r[key]) if spec is None else fmt(r[key], spec) for key, _, spec in columns]
            for _, r in frame.iterrows()]
    out = {"columns": [title for _, title, _ in columns], "rows": rows,
           "numeric": [spec is not None for _, _, spec in columns]}
    if bar and len(frame):
        values = frame[bar].astype(float)
        top = values.max() or 1
        out["bar"] = {"col": [key for key, _, _ in columns].index(bar), "values": (values / top).round(3).tolist()}
    return out


def match_label(row):
    stage = row["stage"]
    if stage == "Regular Season" and pd.notna(row["match_week"]):
        stage = f"Week {int(row['match_week'])}"
    return (f"{row['date']} · {stage} · {row['home_team']} {int(row['home_score'])}-"
            f"{int(row['away_score'])} {row['away_team']}")


def score_line(m):
    return f"{m['home_team']} {int(m['home_score'])}-{int(m['away_score'])} {m['away_team']}"


def window_words(info):
    if info["window"] == "full":
        return f"Whole match: {info['passes']:,} completed passes between {info['players']} players."
    if info["until_minute"] is None:
        return f"Starting XI, whole match (no substitutions): {info['passes']:,} completed passes."
    return (f"Starting XI until the first substitution (minute {info['until_minute']:.0f}): "
            f"{info['passes']:,} completed passes.")


def read_settings(args):
    tournament = args.get("tournament") if args.get("tournament") in TOURNAMENTS else TOURNAMENTS[0]
    ms = MATCHES[MATCHES["competition"] == tournament].sort_values(["date", "kick_off"])
    try:
        match_id = int(args.get("match", ""))
    except ValueError:
        match_id = None
    if match_id not in set(ms["match_id"]):
        finals = ms[ms["stage"].str.contains("Final") & ~ms["stage"].str.contains("Semi|Quarter|3rd", case=False)]
        match_id = int((finals if len(finals) else ms)["match_id"].iloc[0])
    m = MATCH_BY_ID.loc[match_id]
    team = args.get("team") if args.get("team") in (m["home_team"], m["away_team"]) else m["home_team"]
    window = args.get("window") if args.get("window") in WINDOWS else "first_sub"
    set_pieces = args.get("setpieces", "1") != "0"
    try:
        min_passes = max(1, min(int(args.get("minpasses", 3)), 15))
    except ValueError:
        min_passes = 3
    return tournament, ms, match_id, m, team, window, set_pieces, min_passes


# ----------------------------------------------------------------------
# One function per tab: each returns the numbers, texts and charts of that tab
# ----------------------------------------------------------------------
def network_tab(match_id, m, team, window, set_pieces, min_passes, c):
    net = get_network(match_id, team, window, set_pieces)
    nodes, edges, info = net["nodes"], net["edges"], net["info"]
    if nodes.empty or info["passes"] == 0:
        return {"available": False, "message": "No completed passes for this team with these settings."}
    colour = c["home"] if team == m["home_team"] else c["away"]
    top = nodes.iloc[0]
    others = nodes.iloc[1:3]
    link = edges.sort_values("passes", ascending=False).iloc[0] if len(edges) else None
    findings = [
        f"**{team}'s passing ran mostly through {top['player']}** ({top['position']}). "
        f"**{top['pagerank']:.0%}** of the team's ball flow ended with him: **{top['vs_average']:.1f} times** "
        f"the team average.",
        "Next: " + " and ".join(f"**{r['player']}** ({r['pagerank']:.0%})" for _, r in others.iterrows()) + ".",
    ]
    if link is not None:
        findings.append(f"Busiest passing link: **{link['passer']} → {link['recipient']}**, "
                        f"{int(link['passes'])} passes.")
    return {
        "available": True,
        "title": f"{team} passing network",
        "match": score_line(m), "stage": m["stage"], "date": m["date"],
        "colour": "home" if team == m["home_team"] else "away",
        "fig": charts.pitch_network(net, colour, min_passes, c),
        "findings": findings,
        "window": window_words(info) + f" PageRank settled after {info['pagerank_rounds']} rounds.",
        "bars": charts.pagerank_bars(nodes, colour, c),
        "table": make_table(nodes, [
            ("rank", "#", "d"), ("player", "Player", None), ("position", "Position", None),
            ("minutes_in_network", "Minutes", ".0f"), ("pagerank", "PageRank", "%"),
            ("vs_average", "x team average", ".2f"), ("passes_made", "Passes made", "d"),
            ("passes_received", "Received", "d"), ("betweenness", "Link-up score", ".2f")], bar="pagerank"),
    }


def versus_tab(match_id, m, window, set_pieces, min_passes, c):
    teams = [(m["home_team"], c["home"], "home"), (m["away_team"], c["away"], "away")]
    nets = [get_network(match_id, t, window, set_pieces) for t, _, _ in teams]
    x_max = max((float(n["nodes"]["pagerank"].max()) for n in nets if len(n["nodes"])), default=0.2) * 1.12

    def facts(net):
        nd, ed, inf = net["nodes"], net["edges"], net["info"]
        if nd.empty:
            return ["-"] * 6
        link = ed.sort_values("passes", ascending=False).iloc[0] if len(ed) else None
        return [f"{inf['passes']:,}", str(inf["players"]), f"{inf['links_used']} of {inf['possible_links']}",
                f"{nd.iloc[0]['player']} ({nd.iloc[0]['pagerank']:.0%})", f"{inf['top3_share']:.0%}",
                f"{link['passer']} → {link['recipient']} ({int(link['passes'])})" if link is not None else "-"]

    labels = ["Completed passes", "Players in the network", "Pairs that passed at least once",
              "Most important player (PageRank)", "Share held by the top 3", "Busiest passing link"]
    fa, fb = facts(nets[0]), facts(nets[1])
    lead = ""
    if len(nets[0]["nodes"]) and len(nets[1]["nodes"]):
        a, b = nets[0]["info"]["top3_share"], nets[1]["info"]["top3_share"]
        more, less = (teams[0][0], teams[1][0]) if a > b else (teams[1][0], teams[0][0])
        lead = (f"**{more}** relied more on a few players: its top 3 held **{max(a, b):.0%}** of the ball flow, "
                f"against **{min(a, b):.0%}** for {less}. A lower share means the passing was spread more evenly.")
    return {
        "teams": [{"name": t, "colour": key, "fig": charts.pitch_network(n, col, min_passes, c, height=400),
                   "window": window_words(n["info"]),
                   "bars": charts.pagerank_bars(n["nodes"], col, c, x_max=x_max) if len(n["nodes"]) else None}
                  for (t, col, key), n in zip(teams, nets)],
        "lead": lead,
        "compare": {"columns": ["", teams[0][0], teams[1][0]], "numeric": [False, False, False],
                    "rows": [[lab, x, y] for lab, x, y in zip(labels, fa, fb)]},
        "window": ("Passes used: the starting XI until each team's first substitution." if window == "first_sub"
                   else "Passes used: the whole match, with every player who came on."),
    }


def leaders_tab(tournament, window, set_pieces, min_minutes, min_matches, position, sort_by, c):
    allnet = all_networks(window, set_pieces)
    d = allnet[(allnet["competition"] == tournament) & (allnet["minutes_in_network"] >= min_minutes)]
    if d.empty:
        return {"available": False, "message": "No players match these filters."}
    g = d.groupby(["player_id", "player", "team"]).agg(
        matches=("match_id", "nunique"), avg_vs=("vs_average", "mean"), avg_share=("pagerank", "mean"),
        times_top=("rank", lambda s: int((s == 1).sum())), received=("passes_received", "sum"),
        position=("position_group", lambda s: s.mode().iloc[0]),
    ).reset_index()
    g = g[g["matches"] >= min_matches]
    if position != "All":
        g = g[g["position"] == position]
    if g.empty:
        return {"available": False, "message": "No players match these filters. Try fewer matches or minutes."}
    order = ["times_top", "avg_vs"] if sort_by == "top" else ["avg_vs", "times_top"]
    g = g.sort_values(order, ascending=False).reset_index(drop=True)
    g.insert(0, "place", np.arange(1, len(g) + 1))
    best = g.iloc[0]
    pos_share = d[d["rank"] == 1]["position_group"].value_counts(normalize=True)
    value_col = "times_top" if sort_by == "top" else "avg_vs"
    x_title = "Matches as his team's No. 1" if sort_by == "top" else "Average PageRank (x team average)"
    return {
        "available": True,
        "lead": f"**{best['player']} ({best['team']})** leads {tournament}: on average he held "
                f"**{best['avg_vs']:.2f} times** the team-average share of the ball flow, and was his team's "
                f"No. 1 in **{int(best['times_top'])} of {int(best['matches'])}** matches.",
        "positions": "Who is usually a team's No. 1 in this tournament: "
                     + ", ".join(f"{k.lower()}s {v:.0%}" for k, v in pos_share.items()) + ".",
        "fig": charts.leader_bars(g.head(15), value_col, x_title, c),
        "table": make_table(g.head(50), [
            ("place", "#", "d"), ("player", "Player", None), ("team", "Team", None), ("position", "Position", None),
            ("matches", "Matches", "d"), ("avg_vs", "Avg x team average", ".2f"), ("avg_share", "Avg share", "%"),
            ("times_top", "Team's No. 1", "d"), ("received", "Passes received", ",d")], bar="avg_vs"),
        "count": int(len(g)),
    }


def evaluation_tab(group, c):
    if POTM.empty:
        return {"available": False, "message": "player_of_the_match.csv is missing from the data folder."}
    per_match, summary, _ = evaluation()
    s = summary[summary["group"] == group].set_index("method")
    if s.empty:
        return {"available": False, "message": "No awards in this group."}
    n = int(s["awards"].iloc[0])
    pr, rnd, ga = s.loc["PageRank"], s.loc["Random pick"], s.loc["Goals + assists"]
    combo = s.loc["Goals + assists, then PageRank"]
    ss = s.reindex(METHOD_ORDER).dropna(subset=["top1_pct"])

    if group == "All matches":
        pm = per_match
    elif group in TOURNAMENTS:
        pm = per_match[per_match["competition"] == group]
    else:
        pm = per_match[~per_match["scored_or_assisted"]]
    groups = ["Goalkeeper", "Defender", "Midfielder", "Forward"]
    tops = all_networks("full", True)
    tops = tops[(tops["rank"] == 1) & (tops["match_id"].isin(pm["match_id"]))]
    winners_share = pm["position_group"].value_counts(normalize=True).reindex(groups).fillna(0) * 100
    tops_share = tops["position_group"].value_counts(normalize=True).reindex(groups).fillna(0) * 100

    times = pr["top1_pct"] / rnd["top1_pct"] if rnd["top1_pct"] else float("nan")
    findings = [
        f"PageRank picked the award winner as his team's No. 1 in **{pr['top1_pct']:.0f}%** of matches, "
        f"**{times:.1f} times** as often as a random pick ({rnd['top1_pct']:.0f}%). It also beat simply counting "
        f"passes made ({s.loc['Passes made', 'top1_pct']:.0f}%) and was close to counting passes received "
        f"({s.loc['Passes received', 'top1_pct']:.0f}%).",
        f"Goals + assists found the winner far more often (**{ga['top1_pct']:.0f}%**). The award mostly rewards "
        f"the players who score or set up goals, while PageRank measures who the passing goes through. The "
        f"position chart shows the gap: PageRank's No. 1 is usually a midfielder or a centre-back, while many "
        f"award winners are forwards and goalkeepers.",
        f"The two ideas work best together: rank by goals + assists and let PageRank break the ties (for example "
        f"among players who did not score) and the hit rate becomes **{combo['top1_pct']:.0f}%** "
        f"(top 3: {combo['top3_pct']:.0f}%).",
    ]
    if group == "All matches":
        wc = summary[(summary["group"] == "FIFA World Cup 2022") & (summary["method"] == "PageRank")].iloc[0]
        eu = summary[(summary["group"] == "UEFA Euro 2024") & (summary["method"] == "PageRank")].iloc[0]
        findings.append(f"PageRank agreed more with the Euro 2024 award, chosen by UEFA's expert coaches "
                        f"(top 3: **{eu['top3_pct']:.0f}%**), than with the World Cup 2022 award, chosen by a fan "
                        f"vote (top 3: **{wc['top3_pct']:.0f}%**).")

    detail = pm.sort_values(["competition", "date"]).copy()
    detail["pr_rank"] = detail["rank_PageRank"].astype(int).astype(str) + " of " + detail["team_players"].astype(str)
    detail["ga"] = detail["goals"].astype(str) + " / " + detail["assists"].astype(str)
    detail["hit"] = np.where(detail["rank_PageRank"] == 1, "yes", "")
    return {
        "available": True,
        "tiles": [
            {"label": "PageRank's No. 1 was the Player of the Match", "value": f"{pr['top1_pct']:.0f}%",
             "help": f"{n} awards"},
            {"label": "A random pick from the team would be", "value": f"{rnd['top1_pct']:.0f}%",
             "help": "1 / number of players, on average"},
            {"label": "The winner was in PageRank's top 3", "value": f"{pr['top3_pct']:.0f}%",
             "help": f"random pick: {rnd['top3_pct']:.0f}%"},
            {"label": "The winner was in the top 3 for goals + assists", "value": f"{ga['top3_pct']:.0f}%",
             "help": "the award mostly follows goals"},
        ],
        "fig": charts.method_bars(ss, c),
        "findings": findings,
        "methods": make_table(ss.reset_index(), [
            ("method", "Method", None), ("top1_pct", "Top-1 hit %", ".1f"),
            ("top3_pct", "Top-3 hit %", ".1f"), ("avg_rank", "Average rank", ".1f")]),
        "positions": charts.position_bars(groups, winners_share.values, tops_share.values, c),
        "detail": make_table(detail, [
            ("date", "Date", None), ("match", "Match", None), ("player_of_the_match", "Player of the Match", None),
            ("team", "Team", None), ("position_group", "Position", None), ("ga", "Goals / assists", None),
            ("pr_rank", "PageRank rank", None), ("rank_Passes received", "Passes recv. rank", "d"),
            ("rank_Goals + assists", "G+A rank", "d"), ("team_top_pagerank_player", "Team's PageRank No. 1", None),
            ("hit", "Hit", None)]),
        "count": int(len(pm)),
        "group": group,
    }


def how_tab(match_id, m, team, window, set_pieces, damping, c):
    net = get_network(match_id, team, window, set_pieces)
    W, ids = net["W"], net["ids"]
    if len(ids) == 0 or W.sum() == 0:
        return {"available": False, "message": "No completed passes for this team with these settings."}
    nodes = net["nodes"].set_index("player_id").loc[ids].reset_index()
    names = nodes["player"].tolist()
    colour = c["home"] if team == m["home_team"] else c["away"]

    scores, rounds, history = pe.pagerank(W, damping=damping, keep_history=True)
    check = float(np.abs(scores - pe.pagerank_networkx(W, damping=damping)).max())
    order = np.argsort(-scores)
    top5 = order[:5].tolist()
    received = W.sum(axis=0)
    rho = spearmanr(received, scores).statistic if len(ids) > 2 else float("nan")
    base, _, _ = pe.pagerank(W, damping=config.DAMPING)
    rank_now = (-scores).argsort().argsort() + 1
    rank_base = (-base).argsort().argsort() + 1
    comp = pd.DataFrame({"player": names, "score": scores, "rank": rank_now, "rank_085": rank_base,
                         "received": received, "moved": np.where(rank_now != rank_base, "moved", "")})
    comp = comp.sort_values("rank")

    P = pe.transition_matrix(W)
    a, b = int(order[0]), int(order[1])
    labels = [charts.label_with_shirt(names[i], nodes["jersey"].iloc[i]) for i in order]
    return {
        "available": True,
        "team": team,
        "steps": [
            f"**Count the passes.** {team} has {len(ids)} players in this network, so the pass matrix is "
            f"{len(ids)} x {len(ids)}. Example: {names[b]} passed to {names[a]} **{int(W[b, a])}** times.",
            f"**Turn counts into chances.** {names[b]} made {int(W[b].sum())} completed passes, so the chance that "
            f"his next pass goes to {names[a]} is {int(W[b, a])} / {int(W[b].sum())} = **{P[b, a]:.2f}**.",
            f"**Start everyone equal:** 1 / {len(ids)} = {1 / len(ids):.3f} each.",
            f"**Pass the scores on.** Each round, every player hands his score to his team-mates in proportion to his "
            f"passes. With chance 1 - d = {1 - damping:.2f} the ball 'jumps' to a random player instead (the "
            f"random surfer in Google's version).",
            f"**Repeat until nothing changes.** Here that took **{rounds} rounds**. The scores always add up to 100%.",
        ],
        "formula": ("PR(j) = (1 - d) / n  +  d x  SUM over i of  PR(i) x passes(i -> j) / passes_made(i)"
                    f"\n\nd = {damping:.2f}     n = {len(ids)} players"),
        "check": f"Check: our own PageRank code and the networkx library give the same answer here "
                 f"(biggest difference {check:.1e}). A lower d means more random jumps, so the scores move closer "
                 f"to equal.",
        "convergence": charts.convergence(history[:31], names, top5, len(ids), c),
        "matrix": charts.pass_matrix(W[np.ix_(order, order)], labels, c),
        "scatter": charts.pagerank_vs_received(received, scores, names, set(top5), colour, c),
        "scatter_caption": f"Why not just count passes received? The two agree a lot here (Spearman rank "
                           f"correlation {rho:.2f}, where 1.00 = the same order), but PageRank also asks WHO the "
                           f"passes came from: a pass from a player who is always on the ball counts for more.",
        "ranking": make_table(comp, [("rank", f"Rank at d = {damping:.2f}", "d"), ("player", "Player", None),
                                     ("score", "PageRank", "%"), ("rank_085", "Rank at d = 0.85", "d"),
                                     ("received", "Passes received", ".0f"), ("moved", "", None)]),
        "damping": damping,
    }


def about_tab():
    per = MATCHES.groupby("competition", sort=False).agg(matches=("match_id", "count"),
                                                        passes=("completed_passes", "sum")).reset_index()
    pl = PLAYERS.merge(MATCHES[["match_id", "competition"]], on="match_id")
    per["players"] = per["competition"].map(pl.groupby("competition")["player_id"].nunique())
    teams = pd.concat([MATCHES[["competition", "home_team"]].rename(columns={"home_team": "t"}),
                       MATCHES[["competition", "away_team"]].rename(columns={"away_team": "t"})])
    per["teams"] = per["competition"].map(teams.groupby("competition")["t"].nunique())
    return {"table": make_table(per, [("competition", "Tournament", None), ("matches", "Matches", "d"),
                                      ("teams", "Teams", "d"), ("players", "Players", ",d"),
                                      ("passes", "Completed passes", ",d")]),
            "built": DATA_INFO.get("built_at", "?")}


# ----------------------------------------------------------------------
# Pages and data for the browser
# ----------------------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html", tournaments=TOURNAMENTS, windows=WINDOWS, positions=POSITIONS,
                           eval_groups=EVAL_GROUPS,
                           totals={"matches": int(len(MATCHES)), "passes": int(len(PASSES))})


_plotly_js = None


@app.route("/plotly.js")
def plotly_js():
    """The Plotly drawing library, served from the installed Python package (works without internet)."""
    global _plotly_js
    if _plotly_js is None:
        _plotly_js = get_plotlyjs()
    return Response(_plotly_js, mimetype="application/javascript", headers={"Cache-Control": "max-age=86400"})


@app.route("/api/dashboard")
def api_dashboard():
    """Everything that depends on the chosen match and team."""
    tournament, ms, match_id, m, team, window, set_pieces, min_passes = read_settings(request.args)
    c = charts.colours(request.args.get("theme"))
    return jsonify(clean({
        "tournament": tournament,
        "matches": [{"id": int(r["match_id"]), "label": match_label(r)} for _, r in ms.iterrows()],
        "match": match_id, "teams": [m["home_team"], m["away_team"]], "team": team,
        "window": window, "setpieces": set_pieces, "minpasses": min_passes,
        "status": f"{len(MATCHES)} matches · {len(PASSES):,} completed passes · StatsBomb Open Data",
        "network": network_tab(match_id, m, team, window, set_pieces, min_passes, c),
        "versus": versus_tab(match_id, m, window, set_pieces, min_passes, c),
        "about": about_tab(),
    }))


@app.route("/api/leaders")
def api_leaders():
    tournament, _, _, _, _, window, set_pieces, _ = read_settings(request.args)
    c = charts.colours(request.args.get("theme"))

    def number(name, default, low, high):
        try:
            return max(low, min(int(request.args.get(name, default)), high))
        except ValueError:
            return default

    position = request.args.get("position") if request.args.get("position") in POSITIONS else "All"
    sort_by = "top" if request.args.get("sort") == "top" else "avg"
    return jsonify(clean(leaders_tab(tournament, window, set_pieces, number("minutes", 60, 0, 120),
                                     number("matches", 3, 1, 30), position, sort_by, c)))


@app.route("/api/evaluation")
def api_evaluation():
    group = request.args.get("group") if request.args.get("group") in EVAL_GROUPS else EVAL_GROUPS[0]
    return jsonify(clean(evaluation_tab(group, charts.colours(request.args.get("theme")))))


@app.route("/api/how")
def api_how():
    _, _, match_id, m, team, window, set_pieces, _ = read_settings(request.args)
    try:
        damping = round(min(max(float(request.args.get("damping", config.DAMPING)), 0.05), 0.95), 2)
    except ValueError:
        damping = config.DAMPING
    return jsonify(clean(how_tab(match_id, m, team, window, set_pieces, damping,
                                 charts.colours(request.args.get("theme")))))


if __name__ == "__main__":
    # Work out the slow tables before the website opens, so every tab opens fast
    print("Preparing the PageRank tables for every match (about 10 seconds) ...", flush=True)
    all_networks("first_sub", True)
    evaluation()
    # the whole-match tables are made in the background while you look at the first tab
    threading.Thread(target=lambda: all_networks("full", True), daemon=True).start()
    print("\nOpen http://localhost:5000 in your browser.  (Stop the website with Ctrl+C)\n", flush=True)
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
