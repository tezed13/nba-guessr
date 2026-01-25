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
csv_path = BASE_DIR / "data" / "Player Per Game.csv"
try:
    stats_df = pd.read_csv(csv_path)
    stats_df["season"] = stats_df["season"].astype(int)
except Exception as e:
    stats_df = pd.DataFrame()
    print(f"Error loading CSV: {e}")

# -----------------------------
# Routes
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
