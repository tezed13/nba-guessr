import pandas as pd
from pathlib import Path
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import random

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Load CSV
csv_path = BASE_DIR / "Data" / "Player Per Game.csv"
try:
    stats_df = pd.read_csv(csv_path)
    stats_df["season"] = stats_df["season"].astype(int)
except Exception as e:
    stats_df = pd.DataFrame()
    print(f"Error loading CSV: {e}")

# -----------------------------
# Routes test
# -----------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/guess", response_class=HTMLResponse)
async def guess_page(request: Request, start_season: int, end_season: int, types: str = "all"):
    return templates.TemplateResponse(
        "guess.html",
        {
            "request": request,
            "start_season": start_season,
            "end_season": end_season,
            "types": types.split(",") if types else ["all"]
        }
    )

@app.get("/all_players")
async def all_players():
    if stats_df.empty:
        return JSONResponse({"error": "CSV data not loaded"}, status_code=500)
    return sorted(stats_df["player"].dropna().unique().tolist())

@app.route("/random_player")
def random_player():
    try:
        start_year = int(request.args.get('start_season', 1950))
        end_year = int(request.args.get('end_season', 2025))
        difficulty_types = request.args.get('types', 'starters').split(',')

        # 1. Force columns to lowercase to avoid "GS" vs "gs" errors
        stats_df.columns = [c.lower() for c in stats_df.columns]

        # 2. Filter by Year Range
        mask = (stats_df['season'] >= start_year) & (stats_df['season'] <= end_year)
        temp_df = stats_df[mask]

        # 3. Apply Difficulty Filters
        diff_mask = pd.Series(False, index=temp_df.index)
        
        if 'starters' in difficulty_types:
            # Lower the threshold to 30 or 40 to be safe for shorter seasons
            diff_mask |= (temp_df['gs'] >= 40) 
        if 'bench' in difficulty_types:
            diff_mask |= (temp_df['gs'] >= 5) & (temp_df['gs'] < 40)
        if 'endbench' in difficulty_types:
            diff_mask |= (temp_df['gs'] < 5)

        filtered_df = temp_df[diff_mask]

        # 4. FALLBACK: If filters are too strict, just give any player from those years
        if filtered_df.empty:
            print("Filters too strict, falling back to year-only filter")
            filtered_df = temp_df

        if filtered_df.empty:
            return jsonify({"error": "No players found in this year range"}), 404

        # Pick random player
        random_name = random.choice(filtered_df['player'].unique())
        
        # Get all career years for that player to show in the table
        player_career = stats_df[stats_df['player'] == random_name].sort_values('season', ascending=False)
        
        return jsonify({
            "player_name": random_name,
            "seasons": player_career.to_dict(orient='records')
        })

    except Exception as e:
        print(f"Error in random_player: {e}")
        return jsonify({"error": str(e)}), 500


# List of categories you provided
CATEGORIES = [
    "mp_per_game", "fg_per_game", "fga_per_game", "fg_percent", 
    "x3p_per_game", "x3pa_per_game", "x3p_percent", "x2p_per_game", 
    "x2pa_per_game", "x2p_percent", "e_fg_percent", "ft_per_game", 
    "fta_per_game", "ft_percent", "orb_per_game", "drb_per_game", 
    "trb_per_game", "ast_per_game", "stl_per_game", "blk_per_game", 
    "tov_per_game", "pf_per_game", "pts_per_game"
]

# Mapping teams to Conferences
TEAM_TO_CONF = {
    'ATL': 'Eastern', 'BOS': 'Eastern', 'BKN': 'Eastern', 'NJN': 'Eastern', 'CHA': 'Eastern', 'CHI': 'Eastern', 
    'CLE': 'Eastern', 'DET': 'Eastern', 'IND': 'Eastern', 'MIA': 'Eastern', 'MIL': 'Eastern', 'NYK': 'Eastern', 
    'ORL': 'Eastern', 'PHI': 'Eastern', 'TOR': 'Eastern', 'WAS': 'Eastern', 'WSB': 'Eastern',
    'DAL': 'Western', 'DEN': 'Western', 'GSW': 'Western', 'HOU': 'Western', 'LAC': 'Western', 'LAL': 'Western', 
    'MEM': 'Western', 'MIN': 'Western', 'NOP': 'Western', 'NOH': 'Western', 'OKC': 'Western', 'SEA': 'Western', 
    'PHO': 'Western', 'PHX': 'Western', 'POR': 'Western', 'SAC': 'Western', 'SAS': 'Western', 'UTA': 'Western',
}

# Updated spin_data in app.py
@app.get("/spin_data")
async def spin_data():
    if stats_df.empty:
        return JSONResponse({"error": "No data"}, status_code=500)

    # 1. Randomly pick a season and stat key
    available_seasons = stats_df["season"].unique().tolist()
    chosen_season = random.choice(available_seasons)
    
    stat_map = {
        "pts_per_game": "Points Per Game",
        "trb_per_game": "Rebounds Per Game",
        "ast_per_game": "Assists Per Game",
        "stl_per_game": "Steals Per Game",
        "blk_per_game": "Blocks Per Game",
        "tov_per_game": "Turnovers Per Game",
        "pf_per_game": "Fouls Per Game",
        "fta_per_game": "Free Attempts Per Game",
        "fg3a_per_game": "Three Pointers Attempted Per Game",
        "fga_per_game": "Shots Attempted Per Game",
        "mp_per_game": "Minutes Per Game"
    }
    chosen_stat_key = random.choice(list(stat_map.keys()))
    
    # 2. Filter for qualified players (>40 games)
    season_df = stats_df[(stats_df["season"] == chosen_season) & (stats_df["g"] > 40)].copy()
    if season_df.empty: return await spin_data()

    # 3. Find the leader
    leader_row = season_df.sort_values(by=chosen_stat_key, ascending=False).iloc[0]
    
    # 4. Get Hints
    team_abbrev = leader_row["tm"]
    player_conf = TEAM_TO_CONF.get(team_abbrev, "East") # Default to East if missing

    return {
        "winner": leader_row["player"],
        "clues": {
            "stat_name": stat_map[chosen_stat_key],
            "stat_val": str(leader_row[chosen_stat_key]),
            "season": str(chosen_season),
            "pos": leader_row["pos"],
            "conf": player_conf
        }
    }
@app.get("/spin", response_class=HTMLResponse)
async def spin_page(request: Request):
    return templates.TemplateResponse("spin.html", {"request": request})