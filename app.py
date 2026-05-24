import random
import pandas as pd
from pathlib import Path
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ---------------------------------------------------------------------------
# Load & normalise CSV once at startup
# ---------------------------------------------------------------------------

csv_path = BASE_DIR / "Data" / "Player Per Game.csv"

try:
    stats_df = pd.read_csv(csv_path)
    # Normalise all column names to lowercase once — not inside a route
    stats_df.columns = [c.lower() for c in stats_df.columns]
    stats_df["season"] = stats_df["season"].astype(int)
    print(f"Loaded {len(stats_df)} rows from CSV.")
except Exception as e:
    stats_df = pd.DataFrame()
    print(f"Error loading CSV: {e}")

# ---------------------------------------------------------------------------
# Conference mapping
# ---------------------------------------------------------------------------

TEAM_TO_CONF = {
    "ATL": "Eastern", "BOS": "Eastern", "BKN": "Eastern", "NJN": "Eastern",
    "CHA": "Eastern", "CHI": "Eastern", "CLE": "Eastern", "DET": "Eastern",
    "IND": "Eastern", "MIA": "Eastern", "MIL": "Eastern", "NYK": "Eastern",
    "ORL": "Eastern", "PHI": "Eastern", "TOR": "Eastern", "WAS": "Eastern",
    "WSB": "Eastern",
    "DAL": "Western", "DEN": "Western", "GSW": "Western", "HOU": "Western",
    "LAC": "Western", "LAL": "Western", "MEM": "Western", "MIN": "Western",
    "NOP": "Western", "NOH": "Western", "OKC": "Western", "SEA": "Western",
    "PHO": "Western", "PHX": "Western", "POR": "Western", "SAC": "Western",
    "SAS": "Western", "UTA": "Western",
}

# Stat map — keys must match the actual (lowercased) CSV column names.
# Using x3p / x3pa to match the CATEGORIES list in the original code.
STAT_MAP = {
    "pts_per_game":  "Points Per Game",
    "trb_per_game":  "Rebounds Per Game",
    "ast_per_game":  "Assists Per Game",
    "stl_per_game":  "Steals Per Game",
    "blk_per_game":  "Blocks Per Game",
    "tov_per_game":  "Turnovers Per Game",
    "pf_per_game":   "Fouls Per Game",
    "fta_per_game":  "Free Throw Attempts Per Game",
    "x3pa_per_game": "Three-Pointers Attempted Per Game",
    "fga_per_game":  "Shots Attempted Per Game",
    "mp_per_game":   "Minutes Per Game",
}

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/guess", response_class=HTMLResponse)
async def guess_page(
    request: Request,
    start_season: int = Query(...),
    end_season: int = Query(...),
    types: str = Query("all"),
):
    return templates.TemplateResponse(
        request,
        "guess.html",
        {
            "start_season": start_season,
            "end_season": end_season,
            "types": types.split(",") if types else ["all"],
        },
    )


@app.get("/spin", response_class=HTMLResponse)
async def spin_page(request: Request):
    return templates.TemplateResponse(request, "spin.html")

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/all_players")
async def all_players():
    if stats_df.empty:
        return JSONResponse({"error": "CSV data not loaded"}, status_code=500)
    players = sorted(stats_df["player"].dropna().unique().tolist())
    return players


@app.get("/random_player")
async def random_player(
    start_season: int = Query(2000),
    end_season: int = Query(2025),
    types: str = Query("starters"),
):
    try:
        if stats_df.empty:
            return JSONResponse({"error": "Database is empty"}, status_code=500)

        # Clean the types param — guard against bracket/quote artifacts from the URL
        clean_types = types.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
        type_list = [t.strip() for t in clean_types.split(",")]

        # Filter by season range
        mask = (stats_df["season"] >= start_season) & (stats_df["season"] <= end_season)
        pool = stats_df[mask]

        if pool.empty:
            return JSONResponse({"error": "No players in this year range"}, status_code=404)

        # Filter by difficulty (games started)
        diff_mask = pd.Series(False, index=pool.index)
        if "starters" in type_list or "all" in type_list:
            diff_mask |= pool["gs"] >= 40
        if "bench" in type_list or "all" in type_list:
            diff_mask |= (pool["gs"] >= 5) & (pool["gs"] < 40)
        if "endbench" in type_list or "all" in type_list:
            diff_mask |= pool["gs"] < 5

        filtered = pool[diff_mask]
        if filtered.empty:
            filtered = pool  # fallback: use full pool

        # Pick a random player and return their full career stats
        random_name = random.choice(filtered["player"].unique())
        career = (
            stats_df[stats_df["player"] == random_name]
            .sort_values("season", ascending=False)
        )

        seasons = career.where(career.notna(), other=None).to_dict(orient="records")
        return JSONResponse({
            "player_name": random_name,
            "seasons": seasons,
        })

    except Exception as e:
        print(f"CRASH LOG /random_player: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/spin_data")
async def spin_data():
    if stats_df.empty:
        return JSONResponse({"error": "No data"}, status_code=500)

    try:
        # Only use stat keys that actually exist as columns in the DataFrame
        available_stat_keys = [k for k in STAT_MAP if k in stats_df.columns]
        if not available_stat_keys:
            return JSONResponse({"error": "No matching stat columns found in CSV"}, status_code=500)

        chosen_stat_key = random.choice(available_stat_keys)

        # Pick a season that has qualified players (>40 games) for the chosen stat
        # Retry up to 10 times to avoid an infinite recursion loop
        for _ in range(10):
            available_seasons = stats_df["season"].unique().tolist()
            chosen_season = random.choice(available_seasons)

            season_df = stats_df[
                (stats_df["season"] == chosen_season) &
                (stats_df["g"] > 40) &
                stats_df[chosen_stat_key].notna()
            ].copy()

            if not season_df.empty:
                break
        else:
            return JSONResponse({"error": "Could not find valid season/stat combination"}, status_code=500)

        # Find the stat leader
        leader_row = season_df.sort_values(by=chosen_stat_key, ascending=False).iloc[0]
        team_abbrev = str(leader_row.get("tm", "")).upper()

        return JSONResponse({
            "winner": leader_row["player"],
            "clues": {
                "stat_name": STAT_MAP[chosen_stat_key],
                "stat_val": str(round(float(leader_row[chosen_stat_key]), 1)),
                "season": str(chosen_season),
                "pos": leader_row.get("pos", "N/A"),
                "conf": TEAM_TO_CONF.get(team_abbrev, "Unknown"),
            },
        })

    except Exception as e:
        print(f"CRASH LOG /spin_data: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
