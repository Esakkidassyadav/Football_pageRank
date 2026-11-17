# Who Runs the Team? Player Influence Ranking in Football using PageRank on Passing Networks

Web Data Mining mini-project. Every completed pass in a football match is treated as a link from one
player to another, like a hyperlink between two web pages. PageRank, the link-analysis method Google
first used to rank web pages, then finds the players a team's passing runs through.

Data: 230 real matches (FIFA World Cup 2022, UEFA Euro 2024, Indian Super League 2021/22) and
171,879 completed passes from **StatsBomb Open Data**.

## How to run it (Windows)

**Easiest:** double-click `run_project.bat`. The first time it makes a private Python environment
and installs the libraries (needs internet once). Then the website opens at http://localhost:5000.
Close the black window to stop it.

**By hand**, in Command Prompt inside this folder:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000. It takes about 10 seconds to start, because it works out PageRank
for every team in every match first. After that it works without internet.

Optional, in the terminal:

```
python evaluate.py      # the Player of the Match check, printed as tables
python data_prep.py     # download the raw data again from StatsBomb (about 650 MB) and rebuild the tables
python data_prep.py --list   # every free StatsBomb tournament (add one in config.py)
```

## Files

| File | What it does |
|---|---|
| `config.py` | All settings: tournaments, file names, PageRank's damping factor |
| `data_prep.py` | **Step 1.** Downloads StatsBomb's JSON files and keeps what the project needs |
| `pagerank_engine.py` | **Step 2.** Builds the passing network and runs PageRank (written by hand) |
| `evaluate.py` | **Step 3.** Compares PageRank with the official Player of the Match |
| `app.py` | **Step 4.** The website (Flask): answers the browser with data |
| `charts.py` | Every chart (Plotly) |
| `templates/index.html` | The page |
| `static/app.js` | Fills the page in and draws the charts in the browser |
| `static/style.css` | The look (the same glass design as the stock-market project) |
| `data/matches.csv` | 230 matches |
| `data/players.csv` | 7,065 rows: one per player per match (minutes, position, goals, passes) |
| `data/passes.csv.gz` | 171,879 completed passes (who passed, who received, where, when) |
| `data/player_of_the_match.csv` | The official award for all 115 World Cup 2022 and Euro 2024 matches, with sources |
| `run_project.bat` | One-click start on Windows |

## The website

| Tab | What it shows |
|---|---|
| Pass network | One team's passing network on a pitch: circle size = PageRank, line thickness = passes |
| Team vs team | Both teams side by side, and how much each relied on a few players |
| Tournament leaders | The players their team ran through most often, across a whole tournament |
| Player of the Match check | The evaluation: how often PageRank's No. 1 was the official Player of the Match |
| How PageRank works | The algorithm step by step on the chosen team, with a damping-factor slider |
| About the data | Sources, cleaning steps and the size of the data |

## Results (Player of the Match check, 115 matches)

| Method | Top-1 hit | Top-3 hit |
|---|---|---|
| Random pick | 6% | 19% |
| Passes made | 7% | 18% |
| Passes received | 13% | 31% |
| **PageRank** | **16%** | **32%** |
| Goals + assists | 37% | 70% |
| Goals + assists, ties broken by PageRank | 40% | 71% |

PageRank finds the award winner about 2.4 times as often as chance, but the award mostly follows
goals. PageRank measures something different: who the passing goes through (usually a central
midfielder or a centre-back). PageRank agreed more with Euro 2024's expert-chosen award (top 3: 39%)
than with World Cup 2022's fan vote (top 3: 27%).

## Credits

- **Data:** StatsBomb Open Data, https://github.com/statsbomb/open-data. StatsBomb ask anyone who
  publishes or shares work based on this data to name StatsBomb as the source and use their logo
  (from their media pack). Used here for education.
- **Player of the Match lists:** Goal.com (World Cup 2022) and UEFA.com (Euro 2024); the links are in
  `data/player_of_the_match.csv`.
- **PageRank:** S. Brin and L. Page, "The anatomy of a large-scale hypertextual Web search engine" (1998).
- **Design:** the glass technique follows OpenGlass UI (MIT licence, `static/licenses/`). Fonts: Inter
  and Newsreader (SIL Open Font License, `static/fonts/`).
