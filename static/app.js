/*
  app.js - runs in the browser.
  It asks the Python server (app.py) for data, fills in each tab, and draws
  the charts with Plotly. No framework: plain JavaScript.
*/
"use strict";
/* global Plotly */   // the chart library: the page loads it from /plotly.js before this file

const APP = window.APP;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const TABS = [
  ["network", "Pass network"], ["versus", "Team vs team"], ["leaders", "Tournament leaders"],
  ["evaluation", "Player of the Match check"], ["how", "How PageRank works"], ["about", "About the data"],
];

// what the user has chosen
const state = {
  tournament: APP.tournaments[0], match: null, team: null, window: "first_sub", setpieces: true, minpasses: 3,
  tab: null, shown: false, data: null, rendered: new Set(),
  sort: "avg", evalGroup: APP.evalGroups[0], damping: 0.85,
  extra: {},                       // the tabs that ask the server for their own data, by tab name
};

// ---------------------------------------------------------------- helpers
const esc = (text) => String(text ?? "").replace(/[&<>"']/g,
  (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const minus = (text) => String(text ?? "").replace(/(^|[\s(=*])-(?=\d)/g, "$1−");
const rich = (text) => minus(esc(text)).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");   // **bold**
const theme = () => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`the server answered ${response.status}`);
  return response.json();
}

// opts.highlight: mark the row whose first cell is this text
// opts.tone:      "home" or "away": the colour of the small bars inside a column (table.bar)
function tableHTML(table, opts = {}) {
  if (!table) return "";
  const numeric = table.numeric || [];
  const bar = table.bar;
  const cell = (value, i, r) => {
    const text = String(value ?? "");
    if (bar && i === bar.col) {
      const w = Math.max(2, Math.round(64 * (bar.values[r] || 0)));
      return `<td class="num"><span class="cellbar ${opts.tone || ""}"><i style="width:${w}px"></i>${minus(esc(text))}</span></td>`;
    }
    const kind = numeric[i] ? "num" : /^\d{4}-\d{2}-\d{2}$/.test(text) ? "date" : "";
    return `<td class="${kind}">${numeric[i] ? minus(esc(text)) : esc(text)}</td>`;
  };
  const rowClass = (row) => (opts.highlight !== undefined && row[0] === String(opts.highlight) ? "is-selected" : "");
  return `<div class="table-scroll${opts.tall ? " tall" : ""}"><table class="data"><thead><tr>${
    table.columns.map((c, i) => `<th class="${numeric[i] ? "num" : ""}">${esc(c)}</th>`).join("")
  }</tr></thead><tbody>${
    table.rows.map((row, r) => `<tr class="${rowClass(row)}">${row.map((v, i) => cell(v, i, r)).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}

const tile = (t) => `<div class="tile"><div class="label">${esc(t.label)}</div><div class="value">${minus(esc(t.value))}</div>${
  t.help ? `<div class="help">${minus(esc(t.help))}</div>` : ""}</div>`;

function notice(panel, message) {
  panel.innerHTML = `<div class="notice"><p>${esc(message)}</p></div>`;
}

// ---------------------------------------------------------------- the glass thumb
// Tabs and segmented controls show the chosen item with one piece of glass (the "thumb")
// that slides to it. The script only measures where the chosen item is; the CSS moves it.
const thumbWatcher = new ResizeObserver((entries) => entries.forEach((entry) => placeThumb(entry.target)));

function placeThumb(group) {
  const thumb = group.querySelector(":scope > .thumb");
  const chosen = group.querySelector(':scope > [aria-selected="true"], :scope > [aria-pressed="true"]');
  if (!thumb || !chosen || !chosen.offsetWidth) return;      // hidden right now: measured again when shown
  group.style.setProperty("--thumb-x", `${chosen.offsetLeft}px`);
  group.style.setProperty("--thumb-y", `${chosen.offsetTop}px`);
  group.style.setProperty("--thumb-w", `${chosen.offsetWidth}px`);
  group.style.setProperty("--thumb-h", `${chosen.offsetHeight}px`);
  if (group.dataset.thumb !== "ready") {
    group.dataset.thumb = "ready";
    requestAnimationFrame(() => requestAnimationFrame(() => { group.dataset.thumbMoves = ""; }));
  }
}

function setUpThumbs(root = document) {
  $$(".tabs, .segmented", root).forEach((group) => {
    if (!group.querySelector(":scope > .thumb")) {
      group.insertAdjacentHTML("afterbegin", '<i class="thumb" aria-hidden="true"></i>');
      thumbWatcher.observe(group);
    }
    placeThumb(group);
  });
}

// ---------------------------------------------------------------- charts
// Most charts also get a "show as a table" twin, so no number is reachable only by hovering.
function figureTable(fig) {
  const number = (v) => (typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(3)) : (v ?? ""));
  const traces = fig.data.filter((t) => t.hoverinfo !== "skip" && t.mode !== "text");
  if (!traces.length) return null;
  const heat = traces.find((t) => t.type === "heatmap");
  if (heat) {
    return { columns: ["passer → receiver", ...heat.x], numeric: [false, ...heat.x.map(() => true)],
             rows: heat.y.map((label, i) => [label, ...heat.z[i].map(number)]) };
  }
  if (traces.every((t) => t.type === "bar")) {
    const sideways = traces[0].orientation === "h";
    const labelsOf = (t) => (sideways ? t.y : t.x);
    const valuesOf = (t) => (sideways ? t.x : t.y);
    const labels = [];
    traces.forEach((t) => labelsOf(t).forEach((label) => { if (!labels.includes(label)) labels.push(label); }));
    if (sideways && fig.layout.yaxis?.autorange !== "reversed") labels.reverse();   // sideways bars are drawn bottom-up
    return {
      columns: ["", ...traces.map((t) => t.name || "value")], numeric: [false, ...traces.map(() => true)],
      rows: labels.map((label) => [label, ...traces.map((t) => {
        const i = labelsOf(t).indexOf(label);
        return i < 0 ? "" : number(valuesOf(t)[i]);
      })]),
    };
  }
  if (traces.every((t) => t.type === "scatter" && (t.mode || "").includes("lines"))) {   // lines over rounds
    return { columns: ["Round", ...traces.map((t) => t.name)], numeric: [true, ...traces.map(() => true)],
             rows: traces[0].x.map((x, i) => [String(x), ...traces.map((t) => number(t.y[i]))]) };
  }
  return null;
}

function plot(id, fig, opts = {}) {
  const box = document.getElementById(id);
  if (!box) return;
  let twin = box.nextElementSibling;
  if (!fig) {
    Plotly.purge(box);
    box.innerHTML = "";
    if (twin && twin.classList.contains("table-view")) twin.remove();
    return;
  }
  Plotly.react(box, fig.data, fig.layout, { displayModeBar: false, responsive: true });
  const table = opts.noTable ? null : figureTable(fig);
  if (!table) return;
  if (!twin || !twin.classList.contains("table-view")) {
    twin = document.createElement("details");
    twin.className = "table-view";
    box.after(twin);
  }
  twin.innerHTML = `<summary>Show these numbers as a table</summary>${tableHTML(table)}`;
}

const teamKey = (d) => `<div class="legend">
  <span><i class="sw home"></i>${esc(d.teams[0])} (home)</span><span><i class="sw away"></i>${esc(d.teams[1])} (away)</span></div>`;

const pitchKey = `<p class="caption">Each circle is a player at his average position when passing or receiving.
  <strong>Circle size = PageRank</strong>. Line thickness = passes between the two players, both ways added.
  A <strong>thick ring</strong> marks the top 3. Point at a circle or a line to read it.</p>`;

// ---------------------------------------------------------------- one function per tab
const RENDER = {
  network(d) {
    const panel = $("#tab-network");
    const n = d.network;
    if (!n.available) return notice(panel, n.message);
    panel.innerHTML = `
      <div class="network-grid">
        <div class="card pitch-card">
          <div class="card-head"><h2>${esc(n.title)}</h2>
            <span class="match-line">${esc(n.match)}</span><span class="caption tight">${esc(n.stage)} · ${esc(n.date)}</span></div>
          <div class="chart" id="c-pitch" role="img" aria-label="${esc(n.title)} drawn on a pitch"></div>
          <label class="inline-slider"><span>Draw a line when a pair made at least <strong id="mp-val">${state.minpasses}</strong> passes</span>
            <input type="range" class="slider" id="minpasses" min="1" max="10" step="1" value="${state.minpasses}"></label>
          ${pitchKey}
        </div>
        <div class="side">
          <section class="card story"><h2>What the network says</h2>
            <ul class="findings">${n.findings.map((f) => `<li>${rich(f)}</li>`).join("")}</ul>
            <p class="caption">${minus(esc(n.window))}</p></section>
          <div class="card"><h2>PageRank, highest first</h2><div class="chart" id="c-prbars"></div></div>
        </div>
      </div>
      <div class="card"><h2>PageRank of every player</h2>${tableHTML(n.table, { highlight: "1", tone: n.colour })}
        <p class="caption"><strong>PageRank</strong> = the player's share of the team's ball flow (all players add up to
        100%). <strong>x team average</strong>: 1.00 means exactly average. <strong>Minutes</strong> = time spent inside this
        network. <strong>Link-up score</strong> (betweenness) = how often he sits on the shortest passing route between two
        team-mates.</p></div>`;
    plot("c-pitch", n.fig, { noTable: true });
    plot("c-prbars", n.bars);
    wireSlider($("#minpasses"));
  },

  versus(d) {
    const panel = $("#tab-versus");
    const v = d.versus;
    panel.innerHTML = `
      ${teamKey(d)}
      <div class="two">${v.teams.map((t, i) => `<div class="card"><h2><i class="sw ${t.colour}"></i>${esc(t.name)}</h2>
        <p class="pitch-note">${minus(esc(t.window))}</p>
        <div class="chart" id="c-vs-${i}"></div></div>`).join("")}</div>
      <section class="card story"><h2>The two networks compared</h2>
        ${v.lead ? `<p class="prose">${rich(v.lead)}</p>` : ""}
        <div class="spaced">${tableHTML(v.compare)}</div>
        <p class="caption">${esc(v.window)} When the two teams made their first substitution at different times,
        their windows differ in length (see above each pitch), so compare shares (%) rather than pass counts.
        Change it in the settings at the top.</p></section>
      <h2 class="section-title">PageRank of every player (same scale for both teams)</h2>
      <div class="two">${v.teams.map((t, i) => `<div class="card"><h3>${esc(t.name)}</h3><div class="chart" id="c-vsb-${i}"></div></div>`).join("")}</div>`;
    v.teams.forEach((t, i) => { plot(`c-vs-${i}`, t.fig, { noTable: true }); plot(`c-vsb-${i}`, t.bars); });
  },

  leaders() { fetchExtra("leaders"); },
  evaluation() { fetchExtra("evaluation"); },
  how() { fetchExtra("how"); },

  about(d) {
    $("#about-table").innerHTML = tableHTML(d.about.table);
    $("#about-built").textContent = `Tables built on ${d.about.built} by data_prep.py.`;
  },
};

// the tabs that have their own question for the server
const EXTRA = {
  leaders: {
    url: () => `/api/leaders?${new URLSearchParams({
      tournament: state.tournament, window: state.window, setpieces: state.setpieces ? "1" : "0",
      minutes: $("#ld-minutes").value, matches: $("#ld-matches").value, position: $("#ld-position").value,
      sort: state.sort, theme: theme() })}`,
    draw(r) {
      const out = $("#leaders-out");
      if (!r.available) { out.innerHTML = `<div class="notice"><p>${esc(r.message)}</p></div>`; return; }
      out.innerHTML = `
        <section class="card story"><p class="prose">${rich(r.lead)}</p>
          <p class="caption">${esc(r.positions)} "Times the team average" makes players of different teams fair to
          compare: a team of 11 shares the ball among fewer people than a team of 16.</p></section>
        <div class="leaders-grid">
          <div class="card"><h2>Top 15</h2><div class="chart" id="c-leaders"></div></div>
          <div class="card"><h2>Top ${Math.min(50, r.count)} of ${r.count} players</h2>${tableHTML(r.table, { tone: "home", tall: true })}</div>
        </div>`;
      plot("c-leaders", r.fig);
    },
  },
  evaluation: {
    url: () => `/api/evaluation?${new URLSearchParams({ group: state.evalGroup, theme: theme() })}`,
    draw(r) {
      const out = $("#eval-out");
      if (!r.available) { out.innerHTML = `<div class="notice"><p>${esc(r.message)}</p></div>`; return; }
      out.innerHTML = `
        <div class="tiles">${r.tiles.map(tile).join("")}</div>
        <div class="two">
          <div class="card"><h2>How often each method found the award winner</h2><div class="chart" id="c-methods"></div></div>
          <section class="card story"><h2>What it means</h2>
            <ul class="findings">${r.findings.map((f) => `<li>${rich(f)}</li>`).join("")}</ul></section>
        </div>
        <div class="two">
          <div class="card"><h2>Where they play</h2><div class="chart" id="c-positions"></div>
            <p class="caption">PageRank rewards the players the ball keeps coming back to. A goalkeeper can win the
            award for his saves, which no passing network can see.</p></div>
          <div class="card"><h2>The numbers</h2>${tableHTML(r.methods, { highlight: "PageRank" })}
            <p class="caption">Top-1 hit = the award winner was the method's No. 1 player in his team. Top-3 hit = he was
            in its top 3. Average rank: 1 is best. Random pick = what choosing a player at random would give.</p></div>
        </div>
        <div class="card"><h2>Every match (${r.count})</h2>${tableHTML(r.detail, { tall: true })}
          <p class="caption">"Hit" = PageRank's No. 1 in the winner's team was the winner himself. The award winners'
          names were matched to StatsBomb's player lists automatically, and all 115 were found.</p></div>`;
      plot("c-methods", r.fig);
      plot("c-positions", r.positions);
    },
  },
  how: {
    url: () => `/api/how?${new URLSearchParams({
      tournament: state.tournament, match: state.match, team: state.team, window: state.window,
      setpieces: state.setpieces ? "1" : "0", damping: state.damping, theme: theme() })}`,
    draw(r) {
      const out = $("#how-out");
      if (!r.available) { out.innerHTML = `<div class="notice"><p>${esc(r.message)}</p></div>`; return; }
      out.innerHTML = `
        <div class="two">
          <section class="card story"><h2>PageRank on ${esc(r.team)}, step by step</h2>
            <ol class="techniques">${r.steps.map((s) => `<li>${rich(s)}</li>`).join("")}</ol>
            <pre class="formula">${esc(r.formula)}</pre>
            <p class="caption">${minus(esc(r.check))}</p></section>
          <div class="card"><h2>The top 5 scores, round by round</h2><div class="chart" id="c-conv"></div>
            <p class="caption">Every line starts at the same value and settles within a few rounds. This is called
            power iteration.</p></div>
        </div>
        <div class="two">
          <div class="card"><h2>The pass matrix: who passed to whom</h2><div class="chart" id="c-matrix"></div>
            <p class="caption">Each square is the number of passes from the player on the left to the player at the
            bottom. This matrix IS the network: PageRank only uses these numbers.</p></div>
          <div class="card"><h2>PageRank vs passes received</h2><div class="chart" id="c-scatter"></div>
            <p class="caption">${minus(esc(r.scatter_caption))}</p></div>
        </div>
        <div class="card"><h2>Ranking at d = ${r.damping.toFixed(2)}</h2>${tableHTML(r.ranking)}
          <p class="caption">"moved" = a different place than with Google's d = 0.85. Move the slider at the top to
          see how the damping factor changes the scores.</p></div>`;
      plot("c-conv", r.convergence);
      plot("c-matrix", r.matrix);
      plot("c-scatter", r.scatter, { noTable: true });
    },
  },
};

async function fetchExtra(name) {
  const job = EXTRA[name];
  const url = job.url();
  if (state.extra[name] === url) return;          // already showing exactly this
  state.extra[name] = url;
  const panel = $(`#tab-${name}`);
  panel.classList.add("stale");
  try {
    const r = await getJSON(url);
    if (state.extra[name] !== url) return;          // a newer question was asked meanwhile
    job.draw(r);
    setUpThumbs(panel);
  } catch (error) {
    delete state.extra[name];
    $(`#${name === "evaluation" ? "eval" : name}-out`).innerHTML =
      `<div class="notice"><p class="error">Could not load this tab: ${esc(error.message)}</p></div>`;
  } finally {
    panel.classList.remove("stale");
  }
}

// ---------------------------------------------------------------- the settings
function showMatches(d) {
  const box = $("#match");
  box.innerHTML = d.matches.map((m) => `<option value="${m.id}">${esc(m.label)}</option>`).join("");
  box.value = String(d.match);
}

function showTeams(d) {
  const group = $("#team-choice");
  thumbWatcher.unobserve(group);
  group.innerHTML = d.teams.map((t, i) => `<button type="button" data-key="team" data-value="${esc(t)}" data-label="${esc(t)}"
    aria-pressed="${t === d.team}"><span><i class="sw ${i === 0 ? "home" : "away"}"></i>${esc(t)}</span></button>`).join("");
  delete group.dataset.thumb;
  delete group.dataset.thumbMoves;
  setUpThumbs(group.parentElement);
}

function syncSegmented(key) {
  $$(`.segmented button[data-key="${key}"]`).forEach((b) => b.setAttribute("aria-pressed", b.dataset.value === String(state[key])));
  $$(`.segmented:has(button[data-key="${key}"])`).forEach(placeThumb);
}

// ---------------------------------------------------------------- tabs and loading
function showTab(name) {
  state.tab = name;
  state.shown = true;
  history.replaceState(null, "", `#${name}`);
  $$("#tabs button").forEach((b) => {
    b.setAttribute("aria-selected", b.dataset.tab === name);
    b.tabIndex = b.dataset.tab === name ? 0 : -1;
  });
  placeThumb($("#tabs"));
  $(`#tabs button[data-tab="${name}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  const top = $("#main").getBoundingClientRect().top + window.scrollY - $(".tabbar").offsetHeight - 38;
  const scrolledPast = window.scrollY > top;
  $$(".panel").forEach((p) => { p.hidden = p.id !== `tab-${name}`; });
  renderTab(name);
  setUpThumbs($(`#tab-${name}`));
  if (scrolledPast) window.scrollTo({ top });
  $$(`#tab-${name} .chart`).forEach((box) => { if (box.data) Plotly.Plots.resize(box); });
}

function renderTab(name) {
  if (!state.data) return;
  if (EXTRA[name]) { RENDER[name](state.data); return; }       // these check for themselves whether to ask again
  if (state.rendered.has(name)) return;
  RENDER[name](state.data);
  state.rendered.add(name);
}

// Charts measure their labels when drawn, so wait for the web fonts first (never longer than 3 seconds)
const fontsReady = Promise.race([
  Promise.all(["400 13px", "600 13px"].map((f) => document.fonts.load(`${f} "Inter"`))),
  new Promise((resolve) => setTimeout(resolve, 3000)),
]).catch(() => {});

let loadCount = 0;
async function loadDashboard() {
  const mine = ++loadCount;
  $("#main").classList.add("stale");
  try {
    const query = new URLSearchParams({
      tournament: state.tournament, window: state.window, setpieces: state.setpieces ? "1" : "0",
      minpasses: state.minpasses, theme: theme() });
    if (state.match) query.set("match", state.match);
    if (state.team) query.set("team", state.team);
    const [d] = await Promise.all([getJSON(`/api/dashboard?${query}`), fontsReady]);
    if (mine !== loadCount) return;                  // the user changed something again meanwhile
    state.data = d;
    Object.assign(state, { tournament: d.tournament, match: d.match, team: d.team });
    $("#tournament").value = d.tournament;
    showMatches(d);
    showTeams(d);
    $("#status").textContent = d.status;
    state.rendered.clear();
    if (state.shown) renderTab(state.tab);
    else showTab(state.tab || "network");
  } catch (error) {
    $("#status").textContent = `Could not load the data: ${error.message}`;
  } finally {
    if (mine === loadCount) $("#main").classList.remove("stale");
  }
}

// ---------------------------------------------------------------- sliders
const fillSlider = (slider) => slider.style.setProperty("--p", (slider.value - slider.min) / (slider.max - slider.min));

let minPassTimer = null;
function wireSlider(slider) {
  if (!slider) return;
  fillSlider(slider);
  slider.addEventListener("input", () => {
    fillSlider(slider);
    $("#mp-val").textContent = slider.value;
    clearTimeout(minPassTimer);
    minPassTimer = setTimeout(() => { state.minpasses = Number(slider.value); loadDashboard(); }, 250);
  });
}

// ---------------------------------------------------------------- the football backdrop
// A faint pitch with a passing network on it, behind the glass. Drawn once for the window's width
// (from a fixed seed, so it is the same picture every visit). Decoration only: hidden from screen
// readers, gone in high-contrast mode and print.
function drawBackdrop() {
  const box = $("#backdrop");
  if (!box) return;
  const w = Math.max(320, document.documentElement.clientWidth);
  if (Math.abs(w - Number(box.dataset.w || 0)) < 24) return;
  box.dataset.w = String(w);
  let seed = 2022;
  const rand = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const H = 1000, f = (v) => v.toFixed(1);
  // the pitch fills the lower part of the window, as if seen from the stand
  const L = Math.min(w * 0.92, 1700), T = 330, B = 960, x0 = (w - L) / 2;
  const X = (u) => x0 + (u / 120) * L, Y = (v) => T + (v / 80) * (B - T);
  const rect = (a, b, c, d) => `M${f(X(a))} ${f(Y(b))}H${f(X(c))}V${f(Y(d))}H${f(X(a))}Z`;
  let lines = rect(0, 0, 120, 80) + `M${f(X(60))} ${f(Y(0))}V${f(Y(80))}` + rect(0, 18, 18, 62) + rect(102, 18, 120, 62)
    + rect(0, 30, 6, 50) + rect(114, 30, 120, 50);
  const rx = (10 / 120) * L, ry = (10 / 80) * (B - T);
  lines += `M${f(X(60) - rx)} ${f(Y(40))}a${f(rx)} ${f(ry)} 0 1 0 ${f(2 * rx)} 0a${f(rx)} ${f(ry)} 0 1 0 ${f(-2 * rx)} 0`;
  // a 4-3-3 shape, nudged a little, for each half
  const shape = [[6, 40], [22, 12], [20, 30], [20, 50], [22, 68], [38, 22], [36, 40], [38, 58], [52, 14], [54, 40], [52, 66]];
  const players = [];
  shape.forEach(([u, v]) => players.push([u + (rand() - 0.5) * 6, v + (rand() - 0.5) * 6]));
  shape.slice(1).forEach(([u, v]) => players.push([120 - u + (rand() - 0.5) * 6, v + (rand() - 0.5) * 6]));
  let links = "";
  for (let i = 0; i < 11; i++) {
    for (let j = i + 1; j < 11; j++) {
      const [a, b] = [players[i], players[j]];
      if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 28 && rand() < 0.8) links += `M${f(X(a[0]))} ${f(Y(a[1]))}L${f(X(b[0]))} ${f(Y(b[1]))}`;
    }
  }
  const dots = players.map(([u, v], i) => `<circle class="${i < 11 ? "bd-home" : "bd-away"}" cx="${f(X(u))}" cy="${f(Y(v))}" r="${f(5 + rand() * 9)}"/>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${w} ${H}" preserveAspectRatio="none" focusable="false">
    <path class="bd-pitch" d="${lines}"/><path class="bd-link" d="${links}"/>${dots}</svg>`;
}

// ---------------------------------------------------------------- wiring
function start() {
  $("#tabs").innerHTML = TABS.map(([key, label]) =>
    `<button type="button" role="tab" id="tabbtn-${key}" data-tab="${key}" data-label="${label}" aria-controls="tab-${key}" aria-selected="false" tabindex="-1">${label}</button>`).join("");
  TABS.forEach(([key]) => $(`#tab-${key}`).setAttribute("aria-labelledby", `tabbtn-${key}`));
  setUpThumbs();
  document.fonts.ready.then(() => $$(".tabs, .segmented").forEach(placeThumb));

  document.addEventListener("click", (event) => {
    const tab = event.target.closest("#tabs button");
    if (tab) return showTab(tab.dataset.tab);
    if (event.target.closest("#damping-reset")) {
      const slider = $("#damping");
      slider.value = "0.85";
      slider.dispatchEvent(new Event("input"));
      return;
    }
    const choice = event.target.closest(".segmented button");
    if (choice) {
      const { key, value } = choice.dataset;
      if (String(state[key]) === value) return;
      state[key] = value;
      syncSegmented(key);
      if (key === "team" || key === "window") loadDashboard();
      else if (key === "sort") fetchExtra("leaders");
      else if (key === "evalGroup") fetchExtra("evaluation");
    }
  });

  // keyboard: Left / Right / Home / End move between the tabs
  $("#tabs").addEventListener("keydown", (event) => {
    const keys = TABS.map(([key]) => key);
    const now = keys.indexOf(state.tab);
    const next = { ArrowRight: (now + 1) % keys.length, ArrowLeft: (now - 1 + keys.length) % keys.length,
                   Home: 0, End: keys.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    showTab(keys[next]);
    $(`#tabbtn-${keys[next]}`).focus();
  });

  $("#tournament").addEventListener("change", (event) => {
    Object.assign(state, { tournament: event.target.value, match: null, team: null });
    loadDashboard();
  });
  $("#match").addEventListener("change", (event) => {
    Object.assign(state, { match: event.target.value, team: null });
    loadDashboard();
  });
  $("#setpieces").addEventListener("change", (event) => { state.setpieces = event.target.checked; loadDashboard(); });

  // Tournament leaders: sliders and the position menu
  let leaderTimer = null;
  [["ld-minutes", "ld-minutes-val"], ["ld-matches", "ld-matches-val"]].forEach(([id, label]) => {
    const slider = $(`#${id}`);
    fillSlider(slider);
    slider.addEventListener("input", () => {
      fillSlider(slider);
      $(`#${label}`).textContent = slider.value;
      clearTimeout(leaderTimer);
      leaderTimer = setTimeout(() => fetchExtra("leaders"), 250);
    });
  });
  $("#ld-position").addEventListener("change", () => fetchExtra("leaders"));

  // How PageRank works: the damping factor
  let dampTimer = null;
  const damping = $("#damping");
  fillSlider(damping);
  damping.addEventListener("input", () => {
    fillSlider(damping);
    $("#damping-val").textContent = Number(damping.value).toFixed(2);
    clearTimeout(dampTimer);
    dampTimer = setTimeout(() => { state.damping = Number(damping.value).toFixed(2); fetchExtra("how"); }, 200);
  });

  // the glint on a main button follows the pointer along its top edge
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.addEventListener("pointermove", (event) => {
      const button = event.target.closest?.("button.primary");
      if (!button) return;
      const box = button.getBoundingClientRect();
      button.style.setProperty("--light-x", `${Math.round(((event.clientX - box.left) / box.width) * 100)}%`);
    }, { passive: true });
  }

  // open the tab named in the address, e.g. http://localhost:5000/#evaluation
  const tabInAddress = () => TABS.map(([key]) => key).find((key) => key === location.hash.slice(1));
  state.tab = tabInAddress() || null;
  addEventListener("hashchange", () => { const tab = tabInAddress(); if (tab && tab !== state.tab) showTab(tab); });

  // redraw in the right colours when the computer switches between light and dark mode
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { state.extra = {}; loadDashboard(); });

  drawBackdrop();
  let backdropTimer = null;
  addEventListener("resize", () => { clearTimeout(backdropTimer); backdropTimer = setTimeout(drawBackdrop, 200); });

  loadDashboard();
}

start();
