"""
config.py - all project settings in one place.

Every other file reads its settings from here. To study another tournament,
add it to COMPETITIONS and run:  python data_prep.py
"""
from pathlib import Path

# ----------------------------------------------------------------------
# Folders and files
# ----------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"                 # raw StatsBomb JSON files (only needed by data_prep.py)

MATCHES_FILE = DATA_DIR / "matches.csv"              # one row per match
PLAYERS_FILE = DATA_DIR / "players.csv"              # one row per player per match
PASSES_FILE = DATA_DIR / "passes.csv.gz"             # every completed pass (compressed)
POTM_FILE = DATA_DIR / "player_of_the_match.csv"     # official awards, used to check the results
DATA_INFO_FILE = DATA_DIR / "data_info.json"         # when and from where the data was made

# ----------------------------------------------------------------------
# Where the data comes from: StatsBomb Open Data (free, on GitHub)
# ----------------------------------------------------------------------
STATSBOMB_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# competition_id and season_id are StatsBomb's own numbers.
# See them all with:  python data_prep.py --list
COMPETITIONS = [
    {"competition_id": 43, "season_id": 106, "label": "FIFA World Cup 2022"},
    {"competition_id": 55, "season_id": 282, "label": "UEFA Euro 2024"},
    {"competition_id": 1238, "season_id": 108, "label": "Indian Super League 2021/22"},
]

# StatsBomb's files mix the 2021/22 club names with today's names for two ISL
# clubs (same team, same team_id). We always use the name from that season.
TEAM_NAME_FIXES = {
    7282: "ATK Mohun Bagan",   # files sometimes say "Mohun Bagan Super Giant" (its name from 2023)
    7289: "Hyderabad",         # files sometimes say "SC Delhi"
}

# ----------------------------------------------------------------------
# PageRank settings
# ----------------------------------------------------------------------
DAMPING = 0.85        # chance the ball "follows a pass" instead of jumping to a random player
TOLERANCE = 1e-10     # stop when the scores change less than this between two rounds
MAX_ROUNDS = 1000     # safety limit on the number of rounds

# Pass kinds that start a set piece. The app can leave these out.
SET_PIECES = {"Corner", "Free Kick", "Throw-in", "Goal Kick", "Kick Off"}

# StatsBomb pitch size (in yards). Every team is recorded attacking left to right.
PITCH_LENGTH = 120
PITCH_WIDTH = 80
