import random
import re
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

csv_path   = BASE_DIR / "Data" / "Player Per Game.csv"
info_path  = BASE_DIR / "Data" / "Player Career Info.csv"
draft_path = BASE_DIR / "Data" / "Draft Pick History.csv"

try:
    stats_df = pd.read_csv(csv_path)
    stats_df.columns = [c.lower() for c in stats_df.columns]
    stats_df["season"] = stats_df["season"].astype(int)
    print(f"Loaded {len(stats_df)} stats rows.")
except Exception as e:
    stats_df = pd.DataFrame()
    print(f"Error loading stats CSV: {e}")

# Player info — height, weight, HOF
try:
    info_df = pd.read_csv(info_path)
    info_df.columns = [c.lower() for c in info_df.columns]

    def inches_to_ft(val):
        try:
            total = int(val)
            return f"{total // 12}'{total % 12}""
        except:
            return None

    info_df["height"] = info_df["ht_in_in"].apply(inches_to_ft)
    info_df["hof"]    = info_df["hof"].fillna("").astype(str).str.strip()
    # Keep only columns we need, keyed by player_id
    info_lookup = info_df.set_index("player_id")[["height", "hof"]].to_dict("index")
    print(f"Loaded {len(info_lookup)} player info rows.")
except Exception as e:
    info_lookup = {}
    print(f"Error loading info CSV: {e}")

# Draft picks — overall pick number, keyed by player_id
try:
    draft_df = pd.read_csv(draft_path)
    draft_df.columns = [c.lower() for c in draft_df.columns]
    # Keep first (earliest) draft entry per player in case of duplicates
    draft_df = draft_df.dropna(subset=["player_id", "overall_pick"])
    draft_df["overall_pick"] = draft_df["overall_pick"].astype(int)
    draft_lookup = draft_df.groupby("player_id")["overall_pick"].first().to_dict()
    print(f"Loaded {len(draft_lookup)} draft pick rows.")
except Exception as e:
    draft_lookup = {}
    print(f"Error loading draft CSV: {e}")

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

@app.get("/debug_columns")
async def debug_columns():
    import math
    safe = {k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v)
            for k, v in stats_df.iloc[0].to_dict().items()} if not stats_df.empty else {}
    return JSONResponse({"columns": stats_df.columns.tolist(), "sample_row": safe})


@app.get("/all_players")
async def all_players():
    if stats_df.empty:
        return JSONResponse({"error": "CSV data not loaded"}, status_code=500)
    players = sorted(stats_df["player"].dropna().unique().tolist())
    return players


@app.get("/random_player")
async def random_player(
    start_season: int = Query(2000),
    end_season: int = Query(2026),
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
        career_raw = stats_df[stats_df["player"] == random_name].copy()

        # ── Normalize traded-player rows ──────────────────────────────────────
        # Replace XTM rows with the actual individual team rows for that season,
        # ordered so the team matching the prior or next season appears last (bottom).
        def normalize_career(df):
            rows = []
            seasons = sorted(df["season"].unique())
            for i, szn in enumerate(seasons):
                szn_rows = df[df["season"] == szn]
                multi = szn_rows["team"].str.match(r"\d+TM", na=False)
                if multi.any():
                    # Get individual team rows only (not the XTM summary)
                    real_rows = szn_rows[~multi].copy()
                    if real_rows.empty:
                        rows.append(szn_rows.iloc[0])
                        continue
                    # Figure out anchor team: team from next season (or prev if last)
                    anchor = None
                    if i + 1 < len(seasons):
                        next_szn = df[df["season"] == seasons[i + 1]]
                        next_teams = next_szn[~next_szn["team"].str.match(r"\d+TM", na=False)]["team"].tolist()
                        if next_teams:
                            anchor = next_teams[0]
                    if anchor is None and i > 0:
                        prev_szn = df[df["season"] == seasons[i - 1]]
                        prev_teams = prev_szn[~prev_szn["team"].str.match(r"\d+TM", na=False)]["team"].tolist()
                        if prev_teams:
                            anchor = prev_teams[-1]
                    # Put anchor team last, others first
                    if anchor:
                        anchor_rows = real_rows[real_rows["team"] == anchor]
                        other_rows  = real_rows[real_rows["team"] != anchor]
                        ordered = pd.concat([other_rows, anchor_rows])
                    else:
                        ordered = real_rows
                    for _, r in ordered.iterrows():
                        rows.append(r)
                else:
                    for _, r in szn_rows.iterrows():
                        rows.append(r)
            result = pd.DataFrame(rows)
            return result.sort_values("season", ascending=False)

        career = normalize_career(career_raw)

        import math
        raw_seasons = career.to_dict(orient="records")
        # Scrub every value — NaN/Inf are not JSON serializable
        clean_seasons = [
            {k: (None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v)
             for k, v in row.items()}
            for row in raw_seasons
        ]
        # Look up height and draft pick via player_id
        player_id = career_raw["player_id"].iloc[0] if "player_id" in career_raw.columns else None
        info  = info_lookup.get(player_id, {})
        pick  = draft_lookup.get(player_id)

        return JSONResponse({
            "player_name": random_name,
            "height":      info.get("height"),
            "hof":         info.get("hof", ""),
            "draft_pick":  int(pick) if pick is not None else None,
            "seasons":     clean_seasons,
        })

    except Exception as e:
        print(f"CRASH LOG /random_player: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/spin_data")
async def spin_data():
    if stats_df.empty:
        return JSONResponse({"error": "No data"}, status_code=500)

    try:
        available_stat_keys = [k for k in STAT_MAP if k in stats_df.columns]
        if not available_stat_keys:
            return JSONResponse({"error": "No matching stat columns found in CSV"}, status_code=500)

        chosen_stat_key = random.choice(available_stat_keys)

        # For traded players the CSV has multiple rows (one per team + a "TOT" total row).
        # Keep only the TOT row when a player appears more than once in a season,
        # otherwise keep their single row. This prevents the same player appearing
        # twice and ensures stats are season totals, not partial-team splits.
        def dedup_season(df):
            counts = df.groupby("player")["player"].transform("count")
            # Keep TOT rows for multi-team players, keep all rows for single-team players
            return df[(counts == 1) | (df["team"].str.match(r"\d+TM"))]

        for _ in range(10):
            chosen_season = random.choice(stats_df["season"].unique().tolist())

            season_df = stats_df[
                (stats_df["season"] == chosen_season) &
                (stats_df["g"] >= 41) &
                stats_df[chosen_stat_key].notna()
            ].copy()

            season_df = dedup_season(season_df)

            if not season_df.empty:
                break
        else:
            return JSONResponse({"error": "Could not find valid season/stat combination"}, status_code=500)

        # Sort descending and take the true leader
        season_df = season_df.sort_values(by=chosen_stat_key, ascending=False)
        leader_row = season_df.iloc[0]

        stat_val = float(leader_row[chosen_stat_key])
        team_abbrev = str(leader_row.get("team", "")).upper()

        # For traded players TOT has no conference — use their last real team
        if re.match(r"\d+TM", team_abbrev):  # traded player — find real last team
            player_rows = stats_df[
                (stats_df["player"] == leader_row["player"]) &
                (stats_df["season"] == chosen_season) &
                (~stats_df["team"].str.match(r"\d+TM", na=False))
            ]
            if not player_rows.empty:
                team_abbrev = player_rows.iloc[-1]["team"].upper()

        print(f"SPIN: {leader_row['player']} | {STAT_MAP[chosen_stat_key]}: {stat_val} | {chosen_season}")

        return JSONResponse({
            "winner": leader_row["player"],
            "clues": {
                "stat_name": STAT_MAP[chosen_stat_key],
                "stat_val": str(round(stat_val, 1)),
                "season": str(chosen_season),
                "pos": leader_row.get("pos", "N/A"),
                "conf": TEAM_TO_CONF.get(team_abbrev, "Unknown"),
            },
        })

    except Exception as e:
        print(f"CRASH LOG /spin_data: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
