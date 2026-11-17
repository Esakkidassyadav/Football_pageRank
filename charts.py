"""
charts.py - builds every chart of the website.

Each function returns a Plotly figure as a plain dictionary. The website
(app.py) sends it to the browser as JSON, and the Plotly JavaScript library
draws it there.

Colours: blue = the home team, orange = the away team (checked for
colour-blind readers). Everything else is drawn in ink. Every colour has a
light-mode and a dark-mode value, matched to the glass surfaces in
static/style.css. The charts' own backgrounds are see-through, so the glass
shows behind them.
"""
import json

import numpy as np
import plotly.graph_objects as go

import config

THEMES = {
    "light": {
        "surface": "#f6f7fb", "ink": "#0f172a", "ink2": "#334155", "muted": "#566378",
        "grid": "rgba(15,23,42,0.08)", "axis": "rgba(15,23,42,0.26)", "quiet": "#c3cad6",
        "home": "#2a78d6", "away": "#de5b24",
        "series": ["#2a78d6", "#de5b24", "#1baf7a", "#eda100", "#e87ba4"],
        "pitch_line": "rgba(15,23,42,0.30)", "pitch_fill": "rgba(27,140,80,0.07)",
        "heat": ["#eaf2fd", "#104281"],
    },
    "dark": {
        "surface": "#1b1d2e", "ink": "#f8fafc", "ink2": "#cbd5e1", "muted": "#a3b0c2",
        "grid": "rgba(255,255,255,0.09)", "axis": "rgba(255,255,255,0.26)", "quiet": "#4a5368",
        "home": "#3987e5", "away": "#d95926",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
        "pitch_line": "rgba(255,255,255,0.30)", "pitch_fill": "rgba(40,180,110,0.08)",
        "heat": ["#16213a", "#86b6ef"],
    },
}
FONT = '"Inter", system-ui, -apple-system, "Segoe UI", sans-serif'
PARTICLES = {"de", "da", "di", "do", "dos", "das", "del", "der", "van", "von", "le", "la", "mac", "al", "el", "ten"}


def colours(theme):
    return THEMES["dark" if theme == "dark" else "light"]


def short_name(name):
    """'Rodrigo De Paul' -> 'De Paul', 'Nicolás Otamendi' -> 'Otamendi', 'Gavi' -> 'Gavi'."""
    words = str(name).split()
    if len(words) <= 1:
        return str(name)
    if len(words) >= 3 and words[-2].lower() in PARTICLES:
        return " ".join(words[-2:])
    return words[-1]


def label_with_shirt(name, jersey):
    """Short name + shirt number, so two players with the same surname stay apart."""
    return f"{short_name(name)} ({int(jersey)})" if jersey is not None and not np.isnan(jersey) else short_name(name)


def _safe(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _finish(fig, c, height, legend=False, bars=None, **layout):
    """
    The look shared by every chart: quiet grid, thin marks, no heavy borders.
    bars="v" (upright bars) or "h" (sideways bars) removes the grid lines on the
    axis that only holds names, so no line runs through a bar or its label.
    """
    settings = dict(
        height=height, autosize=True, showlegend=legend,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=13, color=c["ink2"]),
        margin=dict(l=10, r=16, t=34 if legend else 12, b=10),
        hoverlabel=dict(bgcolor=c["surface"], bordercolor=c["axis"], font=dict(family=FONT, size=13, color=c["ink"])),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=c["ink2"]), traceorder="normal"),
    )
    settings.update(layout)
    fig.update_layout(**settings)
    axis = dict(gridcolor=c["grid"], linecolor=c["axis"], zerolinecolor=c["axis"], zerolinewidth=1,
                tickfont=dict(color=c["muted"]), title_font=dict(color=c["ink2"]), automargin=True)
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    if bars == "v":
        fig.update_xaxes(showgrid=False)
    elif bars == "h":
        fig.update_yaxes(showgrid=False)
    return json.loads(fig.to_json())


def _bar(**kwargs):
    """A bar with a rounded end and no outline."""
    marker = dict(cornerradius=4, line=dict(width=0))
    marker.update(kwargs.pop("marker", {}))
    return go.Bar(marker=marker, **kwargs)


# ----------------------------------------------------------------------
# The pitch and the passing network
# ----------------------------------------------------------------------
def _arc(cx, cy, r, start_deg, end_deg, steps=30):
    t = np.radians(np.linspace(start_deg, end_deg, steps))
    xs, ys = cx + r * np.cos(t), cy + r * np.sin(t)
    return "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))


def _pitch_shapes(c):
    """StatsBomb's pitch: 120 x 80 yards."""
    L, W = config.PITCH_LENGTH, config.PITCH_WIDTH
    line = dict(color=c["pitch_line"], width=1.4)
    box = dict(type="rect", line=line, layer="below")
    dot = dict(type="circle", line=line, fillcolor=c["pitch_line"], layer="below")
    return [
        dict(type="rect", x0=0, y0=0, x1=L, y1=W, line=line, fillcolor=c["pitch_fill"], layer="below"),
        dict(type="line", x0=L / 2, y0=0, x1=L / 2, y1=W, line=line, layer="below"),
        dict(type="circle", x0=L / 2 - 10, y0=W / 2 - 10, x1=L / 2 + 10, y1=W / 2 + 10, line=line, layer="below"),
        {**dot, "x0": L / 2 - 0.5, "y0": W / 2 - 0.5, "x1": L / 2 + 0.5, "y1": W / 2 + 0.5},
        {**box, "x0": 0, "y0": 18, "x1": 18, "y1": 62},
        {**box, "x0": L - 18, "y0": 18, "x1": L, "y1": 62},
        {**box, "x0": 0, "y0": 30, "x1": 6, "y1": 50},
        {**box, "x0": L - 6, "y0": 30, "x1": L, "y1": 50},
        {**box, "x0": -2, "y0": 36, "x1": 0, "y1": 44},
        {**box, "x0": L, "y0": 36, "x1": L + 2, "y1": 44},
        {**dot, "x0": 11.6, "y0": 39.6, "x1": 12.4, "y1": 40.4},
        {**dot, "x0": L - 12.4, "y0": 39.6, "x1": L - 11.6, "y1": 40.4},
        dict(type="path", path=_arc(12, 40, 10, -53.13, 53.13), line=line, layer="below"),
        dict(type="path", path=_arc(L - 12, 40, 10, 126.87, 233.13), line=line, layer="below"),
    ]


def pitch_network(net, colour, min_passes, c, height=470, highlight_top=3):
    """
    One team's passing network on a pitch.
      circle      = a player, at his average position when passing or receiving
      circle size = his PageRank (the circle's AREA grows with it)
      line        = passes between two players, both directions added (thicker = more)
      thick ring  = the top 3 by PageRank (ink-coloured: dark on light pages, light on dark pages)
    """
    nodes, W, ids = net["nodes"], net["W"], net["ids"]
    pos = nodes.set_index("player_id")
    names = pos["player"]
    fig = go.Figure()

    totals = W + W.T
    max_total = totals.max() if totals.size and totals.max() > 0 else 1
    mid_x, mid_y, mid_text = [], [], []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            count = totals[i, j]
            if count < min_passes:
                continue
            a, b = pos.loc[ids[i]], pos.loc[ids[j]]
            if np.isnan(a["avg_x"]) or np.isnan(b["avg_x"]):
                continue
            share = count / max_total
            fig.add_trace(go.Scatter(
                x=[float(a["avg_x"]), float(b["avg_x"])], y=[float(a["avg_y"]), float(b["avg_y"])], mode="lines",
                line=dict(color=colour, width=1 + 9 * share), opacity=round(0.22 + 0.5 * share, 3),
                hoverinfo="skip", showlegend=False))
            mid_x.append(float((a["avg_x"] + b["avg_x"]) / 2))
            mid_y.append(float((a["avg_y"] + b["avg_y"]) / 2))
            mid_text.append(f"{_safe(names[ids[i]])} → {_safe(names[ids[j]])}: {int(W[i, j])}<br>"
                            f"{_safe(names[ids[j]])} → {_safe(names[ids[i]])}: {int(W[j, i])}<br>"
                            f"<b>{int(count)} passes in total</b>")
    if mid_x:   # invisible points in the middle of each line, so pointing at a line explains it
        fig.add_trace(go.Scatter(x=mid_x, y=mid_y, mode="markers", marker=dict(size=14, opacity=0),
                                 text=mid_text, hovertemplate="%{text}<extra></extra>", showlegend=False))

    shown = nodes.dropna(subset=["avg_x", "avg_y"])
    if len(shown):
        pr = shown["pagerank"].to_numpy()
        size = 16 + 38 * np.sqrt(pr / pr.max())
        top = (shown["rank"] <= highlight_top).to_numpy()
        hover = [
            f"<b>{_safe(r.player)}</b> (#{int(r.jersey) if not np.isnan(r.jersey) else '-'})<br>{_safe(r.position)}<br>"
            f"PageRank: {r.pagerank:.1%} of the team's ball flow<br>= {r.vs_average:.2f} x the team average<br>"
            f"Rank in the team: {int(r['rank'])} of {len(nodes)}<br>"
            f"Passes made: {int(r.passes_made)} · received: {int(r.passes_received)}<br>"
            f"Minutes in this network: {r.minutes_in_network:.0f}"
            for _, r in shown.iterrows()]
        fig.add_trace(go.Scatter(
            x=shown["avg_x"].tolist(), y=shown["avg_y"].tolist(), mode="markers+text",
            marker=dict(size=size.tolist(), color=colour,
                        line=dict(color=[c["ink"] if t else c["surface"] for t in top],
                                  width=[2.6 if t else 1.5 for t in top])),
            text=[str(int(j)) if not np.isnan(j) else "" for j in shown["jersey"]],
            textfont=dict(color="#ffffff", size=11), textposition="middle center",
            hovertext=hover, hoverinfo="text", showlegend=False))
        fig.add_trace(go.Scatter(
            x=shown["avg_x"].tolist(), y=(shown["avg_y"] + 2.2 + size / 9).tolist(), mode="text",
            text=[short_name(n) for n in shown["player"]],
            textfont=dict(color=c["ink"], size=11.5), textposition="bottom center",
            hoverinfo="skip", showlegend=False))

    L, Wd = config.PITCH_LENGTH, config.PITCH_WIDTH
    return _finish(
        fig, c, height, shapes=_pitch_shapes(c), margin=dict(l=4, r=4, t=4, b=26), hovermode="closest",
        xaxis=dict(range=[-4, L + 4], showgrid=False, zeroline=False, visible=False, fixedrange=True),
        yaxis=dict(range=[Wd + 4, -4], showgrid=False, zeroline=False, visible=False,
                   scaleanchor="x", scaleratio=1, fixedrange=True),
        annotations=[dict(x=L / 2, y=Wd + 3.4, text="attacking direction  →", showarrow=False, yanchor="top",
                          font=dict(color=c["muted"], size=11.5))])


def pagerank_bars(nodes, colour, c, x_max=None):
    """PageRank of each player, highest on top."""
    nd = nodes.sort_values("pagerank")
    labels = [label_with_shirt(p, j) for p, j in zip(nd["player"], nd["jersey"])]
    fig = go.Figure(_bar(x=nd["pagerank"].round(4).tolist(), y=labels, orientation="h", name="PageRank",
                         marker=dict(color=colour), hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
    x_axis = dict(tickformat=".0%", title="PageRank")
    if x_max:
        x_axis["range"] = [0, x_max]
    return _finish(fig, c, 70 + 24 * len(nd), bars="h", bargap=0.35, xaxis=x_axis)


# ----------------------------------------------------------------------
# Tournament leaders
# ----------------------------------------------------------------------
def leader_bars(top, value_column, x_title, c, hover_suffix=""):
    t = top.iloc[::-1]
    labels = [f"{short_name(p)} ({team})" for p, team in zip(t["player"], t["team"])]
    fig = go.Figure(_bar(
        x=t[value_column].round(3).tolist(), y=labels, orientation="h", name=x_title,
        marker=dict(color=c["home"]),
        customdata=[[int(m), float(s), int(n)] for m, s, n in zip(t["matches"], t["avg_share"], t["times_top"])],
        hovertemplate=("%{y}<br>%{customdata[0]} matches · average share %{customdata[1]:.1%}"
                       "<br>His team's No. 1 in %{customdata[2]} matches<extra></extra>")))
    return _finish(fig, c, 90 + 27 * len(t), bars="h", bargap=0.35, xaxis=dict(title=x_title))


# ----------------------------------------------------------------------
# Player of the Match check
# ----------------------------------------------------------------------
def method_bars(summary, c):
    """Top-1 and top-3 hit rate of every method, read from top to bottom."""
    fig = go.Figure()
    for column, name, colour in (("top1_pct", "Award winner was the method's No. 1 in his team", c["series"][0]),
                                 ("top3_pct", "Award winner was in the method's top 3", c["series"][1])):
        fig.add_trace(_bar(x=summary[column].round(1).tolist(), y=summary.index.tolist(), orientation="h",
                           name=name, marker=dict(color=colour),
                           hovertemplate="%{y}: %{x:.0f}%<extra></extra>"))
    return _finish(fig, c, 400, legend=True, bars="h", barmode="group", bargap=0.34, bargroupgap=0.08,
                   xaxis=dict(range=[0, 100], ticksuffix="%", title="Share of the awards"),
                   yaxis=dict(autorange="reversed"), margin=dict(l=10, r=16, t=56, b=10))


def position_bars(groups, winners, tops, c):
    fig = go.Figure()
    for values, name, colour in ((winners, "Player of the Match winners", c["series"][0]),
                                 (tops, "PageRank No. 1 of each team", c["series"][1])):
        fig.add_trace(_bar(x=groups, y=[round(float(v), 1) for v in values], name=name, marker=dict(color=colour),
                           hovertemplate="%{x}: %{y:.0f}%<extra></extra>"))
    return _finish(fig, c, 340, legend=True, bars="v", barmode="group", bargap=0.42, bargroupgap=0.1,
                   yaxis=dict(ticksuffix="%", title="Share of players"))


# ----------------------------------------------------------------------
# How PageRank works
# ----------------------------------------------------------------------
def convergence(history, names, chosen, n_players, c):
    """The score of the top players after every round of the calculation."""
    fig = go.Figure()
    rounds = list(range(len(history)))
    for k, i in enumerate(chosen):
        fig.add_trace(go.Scatter(x=rounds, y=[round(float(h[i]), 5) for h in history], mode="lines+markers",
                                 name=short_name(names[i]), line=dict(color=c["series"][k], width=2),
                                 marker=dict(size=6),
                                 hovertemplate="Round %{x}: %{y:.2%}<extra>" + _safe(short_name(names[i])) + "</extra>"))
    fig.add_hline(y=1 / n_players, line_dash="dot", line_color=c["axis"],
                  annotation_text="starting score: 1 / players", annotation_position="bottom right",
                  annotation_font=dict(color=c["muted"], size=11.5))
    return _finish(fig, c, 380, legend=True, xaxis=dict(title="Round"),
                   yaxis=dict(title="PageRank score", tickformat=".0%"))


def pass_matrix(W, labels, c):
    """The network as a table of numbers: rows pass to columns."""
    fig = go.Figure(go.Heatmap(z=W.astype(int).tolist(), x=labels, y=labels,
                               colorscale=[[0, c["heat"][0]], [1, c["heat"][1]]], xgap=1, ygap=1,
                               colorbar=dict(title=dict(text="passes", font=dict(color=c["ink2"])), thickness=12,
                                             tickfont=dict(color=c["muted"]), outlinewidth=0),
                               hovertemplate="%{y} → %{x}: %{z} passes<extra></extra>"))
    return _finish(fig, c, 120 + 26 * len(labels), xaxis=dict(title="receiver", tickangle=-45, showgrid=False),
                   yaxis=dict(title="passer", autorange="reversed", showgrid=False))


def pagerank_vs_received(received, scores, names, labelled, colour, c):
    text = [short_name(n) if i in labelled else "" for i, n in enumerate(names)]
    # neighbours in the ranking often sit close together: put their names on alternate sides
    order = list(np.argsort(-np.asarray(scores)))
    side = ["top center" if order.index(i) % 2 == 0 else "bottom center" for i in range(len(names))]
    fig = go.Figure(go.Scatter(
        x=[int(v) for v in received], y=[round(float(v), 4) for v in scores], mode="markers+text", text=text,
        textposition=side, textfont=dict(size=11, color=c["ink2"]), name="Player",
        customdata=[[short_name(n)] for n in names],
        marker=dict(size=10, color=colour, line=dict(color=c["surface"], width=2)),
        hovertemplate="%{customdata[0]}<br>received %{x} passes<br>PageRank %{y:.1%}<extra></extra>"))
    return _finish(fig, c, 380, xaxis=dict(title="Passes received"), yaxis=dict(title="PageRank", tickformat=".0%"))
