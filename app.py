import random
import re
import sqlite3
import pandas as pd
from pathlib import Path
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ---------------------------------------------------------------------------
# Leaderboard DB
# ---------------------------------------------------------------------------

DB_PATH = BASE_DIR / "leaderboard.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL COLLATE NOCASE,
                category    TEXT    NOT NULL,
                wins        INTEGER NOT NULL DEFAULT 0,
                best_streak INTEGER NOT NULL DEFAULT 0,
                updated_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_name_cat
            ON scores (name, category)
        """)
        conn.commit()

init_db()

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
    stats_df = stats_df[stats_df["lg"] == "NBA"].copy()
    print(f"Loaded {len(stats_df)} NBA rows.")
except Exception as e:
    stats_df = pd.DataFrame()
    print(f"Error loading stats CSV: {e}")

try:
    info_df = pd.read_csv(info_path)
    info_df.columns = [c.lower() for c in info_df.columns]

    def inches_to_ft(val):
        try:
            total = int(val)
            feet, inches = total // 12, total % 12
            return str(feet) + "'" + str(inches) + '"'
        except:
            return None

    info_df["height"] = info_df["ht_in_in"].apply(inches_to_ft)
    info_df["hof"]    = info_df["hof"].fillna("").astype(str).str.strip()
    info_lookup = info_df.set_index("player_id")[["height", "hof"]].to_dict("index")
    print(f"Loaded {len(info_lookup)} player info rows.")
except Exception as e:
    info_lookup = {}
    print(f"Error loading info CSV: {e}")

try:
    draft_df = pd.read_csv(draft_path)
    draft_df.columns = [c.lower() for c in draft_df.columns]
    draft_df = draft_df.dropna(subset=["player_id", "overall_pick"])
    draft_df["overall_pick"] = draft_df["overall_pick"].astype(int)
    draft_lookup = draft_df.groupby("player_id")["overall_pick"].first().to_dict()
    print(f"Loaded {len(draft_lookup)} draft pick rows.")
except Exception as e:
    draft_lookup = {}
    print(f"Error loading draft CSV: {e}")

awards_path   = BASE_DIR / "Data" / "Player Award Shares.csv"
allstar_path  = BASE_DIR / "Data" / "All-Star Selections.csv"
eosteams_path = BASE_DIR / "Data" / "End of Season Teams.csv"

def build_awards_lookup():
    awards = {}

    try:
        aw = pd.read_csv(awards_path)
        aw.columns = [c.lower() for c in aw.columns]
        wins = aw[aw["winner"] == True]
        for pid, grp in wins.groupby("player_id"):
            if pid not in awards: awards[pid] = {}
            for award in grp["award"].unique():
                key = award.lower().strip()
                awards[pid][key] = int((grp["award"] == award).sum())
        print(f"Loaded award shares for {len(awards)} players.")
    except Exception as e:
        print(f"Error loading awards CSV: {e}")

    try:
        as_df = pd.read_csv(allstar_path)
        as_df.columns = [c.lower() for c in as_df.columns]
        for pid, grp in as_df.groupby("player_id"):
            if pid not in awards: awards[pid] = {}
            awards[pid]["allstar"] = len(grp)
        print(f"Loaded All-Star data for {as_df['player_id'].nunique()} players.")
    except Exception as e:
        print(f"Error loading All-Star CSV: {e}")

    try:
        eos = pd.read_csv(eosteams_path)
        eos.columns = [c.lower() for c in eos.columns]
        for pid, grp in eos.groupby("player_id"):
            if pid not in awards: awards[pid] = {}
            allnba = grp[grp["type"].str.contains("All-NBA", case=False, na=False)]
            alldef = grp[grp["type"].str.contains("All-Defensive", case=False, na=False)]
            if len(allnba): awards[pid]["allnba"] = len(allnba)
            if len(alldef): awards[pid]["alldef"] = len(alldef)
            first = allnba[allnba["number_tm"] == 1]
            if len(first): awards[pid]["allnba_first"] = len(first)
        print(f"Loaded EOS team data for {eos['player_id'].nunique()} players.")
    except Exception as e:
        print(f"Error loading EOS teams CSV: {e}")

    return awards

awards_lookup = build_awards_lookup()

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
# Leaderboard API routes
# ---------------------------------------------------------------------------

class ScorePayload(BaseModel):
    name: str
    category: str   # e.g. "2000-2025_starters_3g"
    streak: int     # current streak to compare against best

@app.get("/leaderboard")
async def get_leaderboard(category: str = Query(...)):
    """Return top 10 entries for a given category, sorted by best_streak desc then wins desc."""
    category = category.strip()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT name, wins, best_streak
            FROM scores
            WHERE category = ?
            ORDER BY best_streak DESC, wins DESC
            LIMIT 10
            """,
            (category,),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.post("/leaderboard")
async def post_leaderboard(payload: ScorePayload):
    """Upsert a win for (name, category). Increments wins, updates best_streak if higher."""
    name     = payload.name.strip()[:20]   # cap at 20 chars
    category = payload.category.strip()
    streak   = max(0, int(payload.streak))

    if not name or not category:
        return JSONResponse({"error": "name and category are required"}, status_code=400)

    with get_db() as conn:
        # Check if row exists
        existing = conn.execute(
            "SELECT wins, best_streak FROM scores WHERE name = ? AND category = ?",
            (name, category),
        ).fetchone()

        if existing:
            new_wins   = existing["wins"] + 1
            new_streak = max(existing["best_streak"], streak)
            conn.execute(
                """
                UPDATE scores
                SET wins = ?, best_streak = ?, updated_at = strftime('%s','now')
                WHERE name = ? AND category = ?
                """,
                (new_wins, new_streak, name, category),
            )
        else:
            conn.execute(
                """
                INSERT INTO scores (name, category, wins, best_streak)
                VALUES (?, ?, 1, ?)
                """,
                (name, category, streak),
            )
        conn.commit()

    return JSONResponse({"ok": True})

# ---------------------------------------------------------------------------
# Existing API routes (unchanged)
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

        clean_types = types.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
        type_list = [t.strip() for t in clean_types.split(",")]

        mask = (stats_df["season"] >= start_season) & (stats_df["season"] <= end_season)
        pool = stats_df[mask]

        if pool.empty:
            return JSONResponse({"error": "No players in this year range"}, status_code=404)

        if "starters" in type_list or "all" in type_list:
            qual_rows = pool[(pool["g"] >= 58) & (pool["mp_per_game"] >= 30)]
            qualifier  = qual_rows.groupby("player").size()
            starter_names = qualifier[qualifier >= 3].index.tolist()
        else:
            starter_names = []

        diff_mask = pd.Series(False, index=pool.index)
        if starter_names:
            diff_mask |= pool["player"].isin(starter_names)
        if "bench" in type_list or "all" in type_list:
            diff_mask |= (pool["gs"] >= 5) & (pool["gs"] < 40)
        if "endbench" in type_list or "all" in type_list:
            diff_mask |= pool["gs"] < 5

        filtered = pool[diff_mask]
        if filtered.empty:
            filtered = pool

        if "starters" in type_list and starter_names and not ("bench" in type_list or "endbench" in type_list or "all" in type_list):
            eligible = [p for p in filtered["player"].unique() if p in starter_names]
            random_name = random.choice(eligible) if eligible else random.choice(filtered["player"].unique())
        else:
            random_name = random.choice(filtered["player"].unique())
        career_raw = stats_df[stats_df["player"] == random_name].copy()

        def normalize_career(df):
            rows = []
            seasons = sorted(df["season"].unique())
            for i, szn in enumerate(seasons):
                szn_rows = df[df["season"] == szn]
                multi = szn_rows["team"].str.match(r"\d+TM", na=False)
                if multi.any():
                    real_rows = szn_rows[~multi].copy()
                    if real_rows.empty:
                        rows.append(szn_rows.iloc[0])
                        continue
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
        clean_seasons = [
            {k: (None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v)
             for k, v in row.items()}
            for row in raw_seasons
        ]
        player_id = career_raw["player_id"].iloc[0] if "player_id" in career_raw.columns else None
        info   = info_lookup.get(player_id, {})
        pick   = draft_lookup.get(player_id)
        awards = awards_lookup.get(player_id, {})

        return JSONResponse({
            "player_name": random_name,
            "height":      info.get("height"),
            "hof":         info.get("hof", ""),
            "draft_pick":  int(pick) if pick is not None else None,
            "awards": {
                "mvp":          awards.get("nba most valuable player", 0),
                "dpoy":         awards.get("nba defensive player of the year", 0),
                "allstar":      awards.get("allstar", 0),
                "allnba":       awards.get("allnba", 0),
                "allnba_first": awards.get("allnba_first", 0),
                "alldef":       awards.get("alldef", 0),
            },
            "seasons": clean_seasons,
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

        def dedup_season(df):
            counts = df.groupby("player")["player"].transform("count")
            return df[(counts == 1) | (df["team"].str.match(r"\d+TM"))]

        nba_seasons = stats_df[stats_df["lg"] == "NBA"]["season"].unique().tolist()

        for _ in range(20):
            chosen_season = random.choice(nba_seasons)
            season_df = stats_df[
                (stats_df["season"] == chosen_season) &
                (stats_df["lg"] == "NBA") &
                (stats_df["g"] >= 41) &
                stats_df[chosen_stat_key].notna()
            ].copy()
            season_df = dedup_season(season_df)
            if not season_df.empty:
                break
        else:
            return JSONResponse({"error": "Could not find valid season/stat combination"}, status_code=500)

        season_df = season_df.sort_values(by=chosen_stat_key, ascending=False)
        leader_row = season_df.iloc[0]

        stat_val = float(leader_row[chosen_stat_key])
        team_abbrev = str(leader_row.get("team", "")).upper()

        if re.match(r"\d+TM", team_abbrev):
            player_rows = stats_df[
                (stats_df["player"] == leader_row["player"]) &
                (stats_df["season"] == chosen_season) &
                (~stats_df["team"].str.match(r"\d+TM", na=False))
            ].copy()
            if not player_rows.empty:
                team_abbrev = player_rows.sort_values("g", ascending=False).iloc[0]["team"].upper()

        conf = TEAM_TO_CONF.get(team_abbrev, "")
        if not conf:
            player_teams = stats_df[
                (stats_df["player"] == leader_row["player"]) &
                (stats_df["season"] == chosen_season) &
                (~stats_df["team"].str.match(r"\d+TM", na=False))
            ]["team"].tolist()
            for t in player_teams:
                c = TEAM_TO_CONF.get(t.upper(), "")
                if c:
                    conf = c
                    team_abbrev = t.upper()
                    break

        print(f"SPIN: {leader_row['player']} | {STAT_MAP[chosen_stat_key]}: {stat_val} | {chosen_season} | {team_abbrev} ({conf})")

        return JSONResponse({
            "winner": leader_row["player"],
            "clues": {
                "stat_name": STAT_MAP[chosen_stat_key],
                "stat_val": str(round(stat_val, 1)),
                "season": str(chosen_season),
                "pos": leader_row.get("pos", "N/A"),
                "conf": conf if conf else "Unknown",
            },
        })

    except Exception as e:
        print(f"CRASH LOG /spin_data: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
