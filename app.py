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

@app.get("/random_player")
async def random_player(
    start_season: int = 2000,
    end_season: int = 2025,
    types: list[str] = Query(None)
):
    if stats_df.empty:
        return JSONResponse({"error": "CSV not loaded"}, status_code=500)

    types = types or ["starters", "bench", "endbench"]

    # filter by season range
    df = stats_df[(stats_df["season"] >= start_season) & (stats_df["season"] <= end_season)]
    temp = pd.DataFrame()

    if "starters" in types:
        temp = pd.concat([temp, df[df["gs"] >= 60]])
    if "bench" in types:
        temp = pd.concat([temp, df[(df["g"] > 50) & (df["mp_per_game"] > 10)]])
    if "endbench" in types:
        temp = pd.concat([temp, df[(df["g"] > 30) & (df["mp_per_game"] < 10.1)]])

    df = temp.drop_duplicates()

    if df.empty:
        return JSONResponse({"error": "No players found"}, status_code=404)

    row = df.sample(1).iloc[0]
    player_id = row["player_id"]
    player_name = row["player"]

    # return all seasons
    seasons = stats_df[stats_df["player_id"] == player_id].sort_values("season")
    seasons_list = []
    for _, s in seasons.iterrows():
        seasons_list.append({
            "season": int(s["season"]),
            "tm": s["tm"],
            "g": int(s["g"]),
            "gs": int(s["gs"]) if not pd.isna(s["gs"]) else 0,
            "mp_per_game": round(s["mp_per_game"], 1),
            "pts_per_game": round(s["pts_per_game"], 1),
            "ast_per_game": round(s["ast_per_game"], 1),
            "trb_per_game": round(s["trb_per_game"], 1)
        })

    return {"player_name": player_name, "seasons": seasons_list}



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

@app.get("/spin_data")
async def spin_data():
    if stats_df.empty:
        return JSONResponse({"error": "CSV not loaded"}, status_code=500)

    # Filter by your criteria
    qualified = stats_df[(stats_df["g"] > 45) & (stats_df["mp_per_game"] > 12)].copy()
    
    # Map Conference
    qualified['conference'] = qualified['tm'].map(TEAM_TO_CONF).fillna('Other')
    qualified = qualified[qualified['conference'] != 'Other']

    # Pick a random category
    selected_category = random.choice(CATEGORIES)
    
    # Pick a random target row from the whole dataset
    target_row = qualified.sample(1).iloc[0]
    
    # Find the leader in that category for that Year/Pos/Conf
    subset = qualified[
        (qualified['season'] == target_row['season']) & 
        (qualified['pos'] == target_row['pos']) & 
        (qualified['conference'] == target_row['conference'])
    ]
    
    winner_row = subset.loc[subset[selected_category].idxmax()]

    return {
        "clues": {
            "stat_val": f"{winner_row[selected_category]}",
            "stat_name": selected_category.replace('_', ' ').upper(),
            "season": int(winner_row['season']),
            "pos": winner_row['pos'],
            "conf": winner_row['conference']
        },
        "winner": winner_row["player"]
    }

@app.get("/spin", response_class=HTMLResponse)
async def spin_page(request: Request):
    return templates.TemplateResponse("spin.html", {"request": request})