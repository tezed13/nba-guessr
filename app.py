import random
import re
import math
import sqlite3
import hmac
import hashlib
import time
import secrets
import os
import requests
import pandas as pd
from pathlib import Path
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

# ---------------------------------------------------------------------------
# CORS — restrict to your own origin in production
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",")
if not any(ALLOWED_ORIGINS):
    ALLOWED_ORIGINS = ["*"]   # dev fallback; set ALLOWED_ORIGINS env var in prod

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ---------------------------------------------------------------------------
# Game-token signing (prevents arbitrary score submission)
# ---------------------------------------------------------------------------

LEADERBOARD_SECRET = os.environ.get("LEADERBOARD_SECRET", secrets.token_hex(32))
VALID_CATEGORIES   = {"nba", "nfl", "mlb"}

def _sign(category: str, issued_at: int) -> str:
    msg = f"{category}:{issued_at}"
    return hmac.new(LEADERBOARD_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def make_game_token(category: str) -> str:
    ts = int(time.time())
    return f"{category}:{ts}:{_sign(category, ts)}"

def verify_game_token(token: str, category: str, max_age: int = 7200) -> bool:
    """Return True only if the token is valid, untampered, and not expired."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        tok_cat, ts_str, sig = parts
        if tok_cat != category:
            return False
        ts = int(ts_str)
        if time.time() - ts > max_age:
            return False
        return hmac.compare_digest(_sign(category, ts), sig)
    except Exception:
        return False

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
# NBA — Load & normalise CSV once at startup
# ---------------------------------------------------------------------------

csv_path   = BASE_DIR / "Data" / "Player Per Game.csv"
info_path  = BASE_DIR / "Data" / "Player Career Info.csv"
draft_path = BASE_DIR / "Data" / "Draft Pick History.csv"

try:
    stats_df = pd.read_csv(csv_path)
    stats_df.columns = [c.lower() for c in stats_df.columns]
    stats_df["season"] = stats_df["season"].astype(int)
    stats_df = stats_df[stats_df["lg"] == "NBA"].copy()
    print(f"[NBA] Loaded {len(stats_df)} rows.")
except Exception as e:
    stats_df = pd.DataFrame()
    print(f"[NBA] Error loading stats CSV: {e}")

try:
    info_df = pd.read_csv(info_path)
    info_df.columns = [c.lower() for c in info_df.columns]
    def inches_to_ft(val):
        try:
            total = int(val)
            return f"{total // 12}'{total % 12}\""
        except:
            return None
    info_df["height"] = info_df["ht_in_in"].apply(inches_to_ft)
    info_df["hof"]    = info_df["hof"].fillna("").astype(str).str.strip()
    info_lookup = info_df.set_index("player_id")[["height", "hof"]].to_dict("index")
    print(f"[NBA] Loaded {len(info_lookup)} player info rows.")
except Exception as e:
    info_lookup = {}
    print(f"[NBA] Error loading info CSV: {e}")

try:
    draft_df = pd.read_csv(draft_path)
    draft_df.columns = [c.lower() for c in draft_df.columns]
    draft_df = draft_df.dropna(subset=["player_id", "overall_pick"])
    draft_df["overall_pick"] = draft_df["overall_pick"].astype(int)
    draft_lookup = draft_df.groupby("player_id")["overall_pick"].first().to_dict()
    print(f"[NBA] Loaded {len(draft_lookup)} draft pick rows.")
except Exception as e:
    draft_lookup = {}
    print(f"[NBA] Error loading draft CSV: {e}")

awards_path   = BASE_DIR / "Data" / "Player Award Shares.csv"
allstar_path  = BASE_DIR / "Data" / "All-Star Selections.csv"
eosteams_path = BASE_DIR / "Data" / "End of Season Teams.csv"

def build_nba_awards_lookup():
    awards = {}
    try:
        aw = pd.read_csv(awards_path)
        aw.columns = [c.lower() for c in aw.columns]
        wins = aw[aw["winner"] == True]
        for pid, grp in wins.groupby("player_id"):
            if pid not in awards: awards[pid] = {}
            for award in grp["award"].unique():
                awards[pid][award.lower().strip()] = int((grp["award"] == award).sum())
    except Exception as e:
        print(f"[NBA] Awards error: {e}")
    try:
        as_df = pd.read_csv(allstar_path)
        as_df.columns = [c.lower() for c in as_df.columns]
        for pid, grp in as_df.groupby("player_id"):
            if pid not in awards: awards[pid] = {}
            awards[pid]["allstar"] = len(grp)
    except Exception as e:
        print(f"[NBA] All-Star error: {e}")
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
    except Exception as e:
        print(f"[NBA] EOS teams error: {e}")
    return awards

nba_awards_lookup = build_nba_awards_lookup()

NBA_STAT_MAP = {
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

TEAM_TO_CONF_NBA = {
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

# ---------------------------------------------------------------------------
# NFL — Load via nflreadpy at startup (cached to disk after first download)
# ---------------------------------------------------------------------------
# Data strategy:
#   load_rosters(1966-present)       — one row per player-season: team/pos/height/college
#   load_player_stats(1999-present)  — detailed per-season offensive stats
#   load_draft_picks()               — career awards: Pro Bowls, All-Pro, HOF (1980+)
#
# For 1966-1998 seasons the game shows team and position from rosters; detailed
# offensive stats are unavailable from nflverse for that era, so those columns
# show as "—" in the season table.
# ---------------------------------------------------------------------------

NFL_CACHE = BASE_DIR / "Data"
NFL_CACHE.mkdir(parents=True, exist_ok=True)

nfl_stats_df    = pd.DataFrame()   # 1999-present detailed stats (per-season reg)
nfl_rosters_df  = pd.DataFrame()   # 1966-present roster rows   (per-season)
nfl_draft_df    = pd.DataFrame()   # draft picks + career awards

def _sanitise(df: pd.DataFrame) -> pd.DataFrame:
    """Replace NaN/Inf so rows are JSON-safe."""
    for col in df.select_dtypes(include="number").columns:
        df[col] = df[col].apply(
            lambda v: None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v
        )
    return df

def load_nfl_data():
    global nfl_stats_df, nfl_rosters_df, nfl_draft_df
    cache_stats   = NFL_CACHE / "player_stats.parquet"
    cache_rosters = NFL_CACHE / "rosters.parquet"
    cache_draft   = NFL_CACHE / "draft_picks.parquet"

    try:
        import pyarrow.parquet as pq
        import nflreadpy as nfl

        # ── Historical rosters 1966-present ───────────────────────────────
        # Only keep the columns the app actually uses — saves ~70% memory
        ROSTER_COLS = ["gsis_id", "season", "full_name", "player_name",
                       "position", "depth_chart_position", "team", "height", "college"]

        if cache_rosters.exists():
            import pyarrow.parquet as pq
            available = pq.read_schema(cache_rosters).names
            read_cols = [c for c in ROSTER_COLS if c in available and c != "week"]
            nfl_rosters_df = pd.read_parquet(cache_rosters, columns=read_cols)
            print(f"[NFL] Rosters from cache: {len(nfl_rosters_df)} rows, "
                  f"seasons {nfl_rosters_df['season'].min()}-{nfl_rosters_df['season'].max()}")
        else:
            print("[NFL] Downloading rosters 1966-present (first run only)...")
            raw = nfl.load_rosters(seasons=list(range(1966, 2026)))
            df  = raw.to_pandas()
            # Slim to needed columns before any heavy ops
            keep = [c for c in ROSTER_COLS if c in df.columns]
            df   = df[keep]
            if "week" in df.columns:
                df = (df.sort_values("week", ascending=False)
                        .drop_duplicates(subset=["gsis_id", "season"], keep="first")
                        .drop(columns=["week"], errors="ignore"))
            else:
                df = df.drop_duplicates(subset=["gsis_id", "season"], keep="first")
            df.to_parquet(cache_rosters, index=False)
            nfl_rosters_df = df
            print(f"[NFL] Rosters cached: {len(nfl_rosters_df)} rows")

        # ── Detailed per-season offensive stats (1999-present) ────────────
        STATS_COLS = ["player_id", "player_display_name", "season", "recent_team",
                      "position", "attempts", "completions", "passing_yards",
                      "passing_tds", "passing_interceptions", "carries",
                      "rushing_yards", "rushing_tds", "receptions", "targets",
                      "receiving_yards", "receiving_tds", "sack_fumbles"]

        if cache_stats.exists():
            available = pq.read_schema(cache_stats).names
            read_cols = [c for c in STATS_COLS if c in available]
            nfl_stats_df = pd.read_parquet(cache_stats, columns=read_cols)
            print(f"[NFL] Stats from cache: {len(nfl_stats_df)} rows")
        else:
            print("[NFL] Downloading player stats 1999-present (~30s first run)...")
            raw = nfl.load_player_stats(seasons=True, summary_level="reg")
            df  = raw.to_pandas()
            keep = [c for c in STATS_COLS if c in df.columns]
            df   = df[keep]
            df.to_parquet(cache_stats, index=False)
            nfl_stats_df = df
            print(f"[NFL] Stats cached: {len(nfl_stats_df)} rows")

        # ── Draft picks — career awards: Pro Bowls, All-Pro, HOF ─────────
        if cache_draft.exists():
            nfl_draft_df = pd.read_parquet(cache_draft)
            print(f"[NFL] Draft from cache: {len(nfl_draft_df)} rows")
        else:
            print("[NFL] Downloading draft picks...")
            raw = nfl.load_draft_picks()
            nfl_draft_df = raw.to_pandas()
            nfl_draft_df.to_parquet(cache_draft, index=False)
            print(f"[NFL] Draft cached: {len(nfl_draft_df)} rows")

    except Exception as e:
        print(f"[NFL] Data load error: {e}")
        print("[NFL] NFL routes will return errors until data is available.")

load_nfl_data()

# ---------------------------------------------------------------------------
# Build fast lookup dicts
# ---------------------------------------------------------------------------

def _inches_to_ft(val):
    try:
        hi = int(val)
        return f"{hi // 12}\'{hi % 12}\""
    except Exception:
        return None

def build_nfl_lookups():
    player_info    = {}   # gsis_id  -> {height, position, college, display_name}
    draft_info     = {}   # gsis_id  -> {pick, round, probowls, allpro, hof}
    roster_seasons = {}   # name     -> [{season, team, position}, ...]

    if not nfl_rosters_df.empty:
        for _, row in nfl_rosters_df.iterrows():
            gid  = row.get("gsis_id")
            name = (row.get("full_name") or row.get("player_name")
                    or row.get("display_name"))
            pos  = row.get("position") or row.get("depth_chart_position")
            team = row.get("team")
            szn  = row.get("season")

            if gid and gid not in player_info:
                player_info[str(gid)] = {
                    "height":       _inches_to_ft(row.get("height")),
                    "position":     pos,
                    "college":      row.get("college"),
                    "display_name": name,
                }

            if name and szn:
                roster_seasons.setdefault(name, []).append({
                    "season":   int(szn)   if pd.notna(szn)  else None,
                    "team":     str(team)  if pd.notna(team) else None,
                    "position": str(pos)   if pd.notna(pos)  else None,
                })

    if not nfl_draft_df.empty:
        for _, row in nfl_draft_df.iterrows():
            gid   = row.get("gsis_id")
            pname = row.get("player_name")
            info  = {
                "pick":     row.get("pick"),
                "round":    row.get("round"),
                "probowls": int(row.get("probowls") or 0),
                "allpro":   int(row.get("allpro")   or 0),
                "hof":      bool(row.get("hof", False)),
            }
            if gid:
                draft_info[str(gid)] = info
            if pname:
                draft_info.setdefault(f"name:{pname}", info)

    return player_info, draft_info, roster_seasons

nfl_player_info, nfl_draft_info, nfl_roster_seasons = build_nfl_lookups()

NFL_STAT_MAP = {
    "passing_yards":   "Passing Yards",
    "passing_tds":     "Passing TDs",
    "rushing_yards":   "Rushing Yards",
    "rushing_tds":     "Rushing TDs",
    "receptions":      "Receptions",
    "receiving_yards": "Receiving Yards",
    "receiving_tds":   "Receiving TDs",
    "passing_interceptions": "Interceptions Thrown",
    "sack_fumbles":          "Sacks",
}

# Position groups for difficulty tiers
QB_POSITIONS    = {"QB"}
SKILL_POSITIONS = {"WR", "RB", "TE", "FB"}


# ---------------------------------------------------------------------------
# MLB — Load from Rdatasets Lahman CSVs at startup
# ---------------------------------------------------------------------------

MLB_CACHE = BASE_DIR / "Data"

mlb_batting_df  = pd.DataFrame()
mlb_pitching_df = pd.DataFrame()
mlb_people_df   = pd.DataFrame()
mlb_awards_lkp  = {}
mlb_name_map    = {}

def load_mlb_data():
    """Load pre-built parquets. Builds any missing files from Lahman on first run."""
    global mlb_batting_df, mlb_pitching_df, mlb_people_df, mlb_awards_lkp, mlb_name_map

    bat_path = MLB_CACHE / "batting_final.parquet"
    pit_path = MLB_CACHE / "pitching_final.parquet"
    ppl_path = MLB_CACHE / "people_final.parquet"
    aw_path  = MLB_CACHE / "awards_final.parquet"

    LAHMAN = "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/Lahman/"

    def fetch_lahman(fname):
        from io import StringIO
        print(f"[MLB] Downloading {fname}...")
        r = requests.get(LAHMAN + fname, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        if "rownames" in df.columns:
            df = df.drop(columns=["rownames"])
        return df

    def safe_int(s):
        return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)

    if not bat_path.exists() or not aw_path.exists():
        print("[MLB] Building missing parquets from Lahman...")

        if ppl_path.exists():
            ppl_tmp = pd.read_parquet(ppl_path)
            name_map_tmp = ppl_tmp.set_index("playerID")[["fullName"]].to_dict("index")
        else:
            ppl_tmp = fetch_lahman("People.csv")
            ppl_tmp["fullName"] = (ppl_tmp["nameFirst"].fillna("") + " " + ppl_tmp["nameLast"].fillna("")).str.strip()
            name_map_tmp = ppl_tmp.set_index("playerID")[["fullName"]].to_dict("index")

        teams = fetch_lahman("Teams.csv")
        team_name_map = {}
        for _, tr in teams.iterrows():
            tid = str(tr.get("teamID", ""))
            yr  = tr.get("yearID")
            nm  = str(tr.get("name", ""))
            if tid and nm and nm != "nan":
                team_name_map[(tid, int(yr) if pd.notna(yr) else 0)] = nm.split()[-1]

        def friendly_team(tid, yr):
            try: return team_name_map.get((str(tid), int(yr)), str(tid))
            except Exception: return str(tid)

        if not bat_path.exists():
            bat = fetch_lahman("Batting.csv")
            bat = bat[bat["lgID"].isin(["AL", "NL"])].copy()
            bat_cols = ["AB","H","BB","HBP","SF","X2B","X3B","HR","RBI","SB","R","G","SO"]
            for c in bat_cols:
                if c in bat.columns: bat[c] = safe_int(bat[c])
            bat["yearID"] = pd.to_numeric(bat["yearID"], errors="coerce")
            bat_num = [c for c in bat_cols if c in bat.columns]
            bat_agg  = bat.groupby(["playerID","yearID"])[bat_num].sum().reset_index()
            bat_team = (bat.sort_values("G", ascending=False)
                           .groupby(["playerID","yearID"])[["teamID","lgID"]]
                           .first().reset_index())
            bat = bat_agg.merge(bat_team, on=["playerID","yearID"], how="left")
            bat["AVG"] = (bat["H"] / bat["AB"].replace(0, float("nan"))).round(3).fillna(0.0)
            denom = bat["AB"] + bat["BB"] + bat["HBP"] + bat["SF"]
            bat["OBP"] = ((bat["H"] + bat["BB"] + bat["HBP"]) / denom.replace(0, float("nan"))).round(3).fillna(0.0)
            tb = bat["H"] + bat["X2B"] + 2*bat["X3B"] + 3*bat["HR"]
            bat["SLG"] = (tb / bat["AB"].replace(0, float("nan"))).round(3).fillna(0.0)
            bat["OPS"] = (bat["OBP"] + bat["SLG"]).round(3)
            bat["player_name"]   = bat["playerID"].map(lambda p: name_map_tmp.get(p, {}).get("fullName") or p)
            bat["team_friendly"] = bat.apply(lambda r: friendly_team(r["teamID"], r["yearID"]), axis=1)
            bat.to_parquet(bat_path, index=False)
            print(f"[MLB] batting_final.parquet built: {len(bat)} rows")

        if not aw_path.exists():
            aw  = fetch_lahman("AwardsPlayers.csv")
            hof = fetch_lahman("HallOfFame.csv")
            ast = fetch_lahman("AllstarFull.csv")
            awards_rows = {}
            for _, row in aw.iterrows():
                pid = row.get("playerID")
                if not pid: continue
                awards_rows.setdefault(pid, {})
                aid = str(row.get("awardID", "")).lower().strip()
                awards_rows[pid][aid] = awards_rows[pid].get(aid, 0) + 1
            for pid in set(hof[hof["inducted"] == "Y"]["playerID"].tolist()):
                awards_rows.setdefault(pid, {})
                awards_rows[pid]["hof"] = 1
            for pid, grp in ast.groupby("playerID"):
                awards_rows.setdefault(pid, {})
                awards_rows[pid]["allstar"] = len(grp)
            aw_df = pd.DataFrame([{"playerID": pid, **vals} for pid, vals in awards_rows.items()]).fillna(0)
            aw_df.to_parquet(aw_path, index=False)
            print(f"[MLB] awards_final.parquet built: {len(aw_df)} rows")

    missing = [p for p in [bat_path, pit_path, ppl_path, aw_path] if not p.exists()]
    if missing:
        print(f"[MLB] Still missing after build attempt: {[p.name for p in missing]}")
        return

    mlb_batting_df  = pd.read_parquet(bat_path)
    mlb_pitching_df = pd.read_parquet(pit_path)
    mlb_people_df   = pd.read_parquet(ppl_path)

    for _, row in mlb_people_df.iterrows():
        pid = row.get("playerID")
        if pid:
            mlb_name_map[pid] = {
                "fullName":   row.get("fullName"),
                "height_str": row.get("height_str"),
                "bats":       row.get("bats"),
                "throws":     row.get("throws"),
                "position":   row.get("position"),
            }

    aw_df = pd.read_parquet(aw_path)
    for _, row in aw_df.iterrows():
        pid = row.get("playerID")
        if pid:
            mlb_awards_lkp[pid] = {k: v for k, v in row.items() if k != "playerID"}

    print(f"[MLB] Ready — {len(mlb_batting_df)} batting rows, "
          f"{len(mlb_pitching_df)} pitching rows, {len(mlb_people_df)} players")

try:
    load_mlb_data()
except Exception as e:
    import traceback
    print(f"[MLB] Load error: {e}")
    print(traceback.format_exc())

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
    return templates.TemplateResponse(request, "guess.html", {
        "start_season": start_season,
        "end_season": end_season,
        "types": types.split(",") if types else ["all"],
    })

@app.get("/nfl_guess", response_class=HTMLResponse)
async def nfl_guess_page(
    request: Request,
    start_season: int = Query(1970),
    end_season: int = Query(2024),
    types: str = Query("qb"),
):
    return templates.TemplateResponse(request, "nfl_guess.html", {
        "start_season": start_season,
        "end_season": end_season,
        "types": types,
    })

@app.get("/spin", response_class=HTMLResponse)
async def spin_page(request: Request):
    return templates.TemplateResponse(request, "spin.html")

@app.get("/nfl_spin", response_class=HTMLResponse)
async def nfl_spin_page(request: Request):
    return templates.TemplateResponse(request, "nfl_spin.html")

# ---------------------------------------------------------------------------
# Leaderboard API
# ---------------------------------------------------------------------------

class ScorePayload(BaseModel):
    name: str
    category: str
    streak: int
    game_token: str   # required — issued by /game/start

@app.get("/game/start")
async def game_start(category: str = Query(...)):
    """Issue a signed token when a new game round begins."""
    if category not in VALID_CATEGORIES:
        return JSONResponse({"error": "Invalid category"}, status_code=400)
    return JSONResponse({"game_token": make_game_token(category)})

@app.get("/leaderboard")
async def get_leaderboard(category: str = Query(...)):
    if category not in VALID_CATEGORIES:
        return JSONResponse({"error": "Invalid category"}, status_code=400)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT name, best_streak FROM scores
               WHERE category = ?
               ORDER BY best_streak DESC LIMIT 10""",
            (category.strip(),),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])

@app.post("/leaderboard")
async def post_leaderboard(payload: ScorePayload):
    name     = payload.name.strip()[:20]
    category = payload.category.strip()
    streak   = max(0, int(payload.streak))

    if not name or not category:
        return JSONResponse({"error": "name and category required"}, status_code=400)

    if category not in VALID_CATEGORIES:
        return JSONResponse({"error": "Invalid category"}, status_code=400)

    if not verify_game_token(payload.game_token, category):
        return JSONResponse({"error": "Invalid or expired game token"}, status_code=403)

    with get_db() as conn:
        existing = conn.execute(
            "SELECT best_streak FROM scores WHERE name=? AND category=?",
            (name, category),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE scores SET best_streak=?, updated_at=strftime('%s','now')
                   WHERE name=? AND category=?""",
                (max(existing["best_streak"], streak), name, category),
            )
        else:
            conn.execute(
                "INSERT INTO scores (name, category, wins, best_streak) VALUES (?,?,1,?)",
                (name, category, streak),
            )
        conn.commit()
    return JSONResponse({"ok": True})

# ---------------------------------------------------------------------------
# NBA API routes (unchanged)
# ---------------------------------------------------------------------------

@app.get("/all_players")
async def all_players():
    if stats_df.empty:
        return JSONResponse({"error": "CSV data not loaded"}, status_code=500)
    return sorted(stats_df["player"].dropna().unique().tolist())

@app.get("/random_player")
async def random_player(
    start_season: int = Query(2000),
    end_season: int = Query(2026),
    types: str = Query("starters"),
):
    try:
        if stats_df.empty:
            return JSONResponse({"error": "Database is empty"}, status_code=500)
        clean_types = types.replace("[","").replace("]","").replace("'","").replace('"',"")
        type_list = [t.strip() for t in clean_types.split(",")]
        mask = (stats_df["season"] >= max(start_season, 1950)) & (stats_df["season"] <= end_season)
        pool = stats_df[mask]
        if pool.empty:
            return JSONResponse({"error": "No players in this year range"}, status_code=404)
        if "starters" in type_list or "all" in type_list:
            qual_rows = pool[(pool["g"] >= 58) & (pool["mp_per_game"] >= 30)]
            qualifier = qual_rows.groupby("player").size()
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
            seasons = sorted(df["season"].unique())   # ascending: oldest first
            for i, szn in enumerate(seasons):
                szn_rows = df[df["season"] == szn]
                multi = szn_rows["team"].str.match(r"\d+TM", na=False)
                if multi.any():
                    real_rows = szn_rows[~multi].copy()
                    if real_rows.empty:
                        rows.append(szn_rows.iloc[0]); continue

                    # In the final display seasons are descending (newest on top).
                    # We want the row whose team matches the ADJACENT season to sit
                    # next to it visually.
                    #
                    # For a given season szn, the season displayed directly BELOW it
                    # is szn-1 (the older year, index i-1 in ascending array).
                    # The season displayed directly ABOVE it is szn+1 (index i+1).
                    #
                    # Strategy: find which team in this multi-team year matches the
                    # year before (i-1). Put that team at the BOTTOM of this year's
                    # rows so it sits adjacent to the older season below it.
                    # If no match below, try matching the year after (i+1) and put
                    # that team at the TOP so it's adjacent to the newer season above.

                    bottom_anchor = None   # team to place at bottom (matches older year)
                    top_anchor    = None   # team to place at top    (matches newer year)

                    if i > 0:
                        prv = df[df["season"] == seasons[i - 1]]
                        pt  = prv[~prv["team"].str.match(r"\d+TM", na=False)]["team"].tolist()
                        if pt and pt[-1] in real_rows["team"].values:
                            bottom_anchor = pt[-1]

                    if i + 1 < len(seasons):
                        nxt = df[df["season"] == seasons[i + 1]]
                        nt  = nxt[~nxt["team"].str.match(r"\d+TM", na=False)]["team"].tolist()
                        if nt and nt[0] in real_rows["team"].values:
                            top_anchor = nt[0]

                    if bottom_anchor:
                        # Matching row goes last (bottom), others go first (top)
                        ordered = pd.concat([
                            real_rows[real_rows["team"] != bottom_anchor],
                            real_rows[real_rows["team"] == bottom_anchor],
                        ])
                    elif top_anchor:
                        # Matching row goes first (top), others go last (bottom)
                        ordered = pd.concat([
                            real_rows[real_rows["team"] == top_anchor],
                            real_rows[real_rows["team"] != top_anchor],
                        ])
                    else:
                        ordered = real_rows

                    for _, r in ordered.iterrows():
                        rows.append(r)
                else:
                    for _, r in szn_rows.iterrows():
                        rows.append(r)

            return pd.DataFrame(rows).sort_values("season", ascending=False)

        career = normalize_career(career_raw)
        raw_seasons = career.to_dict(orient="records")
        clean_seasons = [{k: (None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v) for k, v in row.items()} for row in raw_seasons]
        player_id = career_raw["player_id"].iloc[0] if "player_id" in career_raw.columns else None
        info   = info_lookup.get(player_id, {})
        pick   = draft_lookup.get(player_id)
        awards = nba_awards_lookup.get(player_id, {})
        return JSONResponse({
            "player_name": random_name,
            "height":     info.get("height"),
            "hof":        info.get("hof", ""),
            "draft_pick": int(pick) if pick is not None else None,
            "awards": {
                "mvp":          awards.get("nba most valuable player", 0),
                "dpoy":         awards.get("nba defensive player of the year", 0),
                "smoy":         awards.get("nba sixth man of the year", 0),
                "mip":          awards.get("nba most improved player", 0),
                "roy":          awards.get("nba rookie of the year", 0),
                "allstar":      awards.get("allstar", 0),
                "allnba":       awards.get("allnba", 0),
                "allnba_first": awards.get("allnba_first", 0),
                "alldef":       awards.get("alldef", 0),
            },
            "seasons": clean_seasons,
        })
    except Exception as e:
        print(f"CRASH /random_player: {e}")
        return JSONResponse({"error": "An internal error occurred"}, status_code=500)

# ---------------------------------------------------------------------------
# NFL API routes
# ---------------------------------------------------------------------------

@app.get("/nfl/all_players")
async def nfl_all_players():
    # Use rosters as the primary name source (covers 1966+), fall back to stats
    if not nfl_rosters_df.empty:
        col = "full_name" if "full_name" in nfl_rosters_df.columns else "player_name"
        players = sorted(nfl_rosters_df[col].dropna().unique().tolist())
        return players
    if not nfl_stats_df.empty:
        return sorted(nfl_stats_df["player_display_name"].dropna().unique().tolist())
    return JSONResponse({"error": "NFL data not loaded"}, status_code=500)

@app.get("/nfl/random_player")
async def nfl_random_player(
    start_season: int = Query(1970),
    end_season:   int = Query(2024),
    types: str = Query("qb"),   # qb | skill | all
):
    try:
        if nfl_rosters_df.empty:
            return JSONResponse({"error": "NFL data not loaded"}, status_code=500)

        t = types.lower().strip()
        name_col = "full_name" if "full_name" in nfl_rosters_df.columns else "player_name"

        # ── Build pool from rosters (covers all of 1966-present) ──────────
        roster_pool = nfl_rosters_df.copy()
        mask = (roster_pool["season"] >= start_season) & (roster_pool["season"] <= end_season)
        roster_pool = roster_pool[mask]

        pos_col = "position" if "position" in roster_pool.columns else "depth_chart_position"
        if t == "qb":
            roster_pool = roster_pool[roster_pool[pos_col] == "QB"]
        elif t == "skill":
            roster_pool = roster_pool[roster_pool[pos_col].isin(SKILL_POSITIONS)]
        else:
            roster_pool = roster_pool[roster_pool[pos_col].isin(QB_POSITIONS | SKILL_POSITIONS)]

        if roster_pool.empty:
            return JSONResponse({"error": "No players match this filter"}, status_code=404)

        # Require players who appeared in at least 5 seasons in the range
        season_counts = roster_pool.groupby(name_col)["season"].nunique()
        five_plus     = set(season_counts[season_counts >= 5].index.tolist())
        eligible_names = list(five_plus) if five_plus else roster_pool[name_col].dropna().unique().tolist()

        random_name = random.choice(eligible_names)

        # ── Resolve gsis_id and metadata via rosters ──────────────────────
        player_rows = nfl_rosters_df[nfl_rosters_df[name_col] == random_name]
        gsis_id     = None
        if "gsis_id" in player_rows.columns:
            gid_vals = player_rows["gsis_id"].dropna()
            if not gid_vals.empty:
                gsis_id = str(gid_vals.iloc[0])

        pinfo = nfl_player_info.get(gsis_id, {}) if gsis_id else {}
        dinfo = (nfl_draft_info.get(gsis_id)
                 or nfl_draft_info.get(f"name:{random_name}", {}))

        position = (pinfo.get("position")
                    or (player_rows[pos_col].dropna().mode().iloc[0]
                        if not player_rows[pos_col].dropna().empty else None))

        def nfl_normalize_seasons(roster_szns, stats_szns):
            """
            Order multi-team seasons so the row matching the adjacent year's team
            sits closest to it visually (display is newest-first / descending).
            """
            all_szns = sorted(set(roster_szns) | set(stats_szns))  # ascending

            # Build per-season buckets
            szn_buckets = {}
            for szn in all_szns:
                if szn in stats_szns:
                    rows = stats_szns[szn] if isinstance(stats_szns[szn], list) else [stats_szns[szn]]
                else:
                    rows = [roster_szns.get(szn, {"season": szn})]
                for r in rows:
                    if not r.get("team") and szn in roster_szns:
                        r["team"] = roster_szns[szn].get("team")
                szn_buckets[szn] = rows

            # For each season, decide ordering of its rows.
            # Display is descending so within a season:
            #   top_anchor (matches newer season above) → goes FIRST in bucket
            #   bottom_anchor (matches older season below) → goes LAST in bucket
            ordered_buckets = {}
            for i, szn in enumerate(all_szns):
                bucket = szn_buckets[szn]
                if len(bucket) == 1:
                    ordered_buckets[szn] = bucket
                    continue

                teams = [r.get("team") for r in bucket]

                # Newer season is displayed above → its team should be at TOP of this bucket
                top_anchor = None
                if i + 1 < len(all_szns):
                    newer_bucket = szn_buckets[all_szns[i + 1]]
                    newer_team = newer_bucket[0].get("team")
                    if newer_team and newer_team in teams:
                        top_anchor = newer_team

                # Older season is displayed below → its team should be at BOTTOM of this bucket
                bottom_anchor = None
                if i > 0:
                    older_bucket = szn_buckets[all_szns[i - 1]]
                    older_team = older_bucket[-1].get("team")
                    if older_team and older_team in teams:
                        bottom_anchor = older_team

                if top_anchor:
                    ordered = [r for r in bucket if r.get("team") == top_anchor] + \
                              [r for r in bucket if r.get("team") != top_anchor]
                elif bottom_anchor:
                    ordered = [r for r in bucket if r.get("team") != bottom_anchor] + \
                              [r for r in bucket if r.get("team") == bottom_anchor]
                else:
                    ordered = bucket

                ordered_buckets[szn] = ordered

            # Output descending (newest first)
            result = []
            for szn in reversed(all_szns):
                result.extend(ordered_buckets[szn])
            return result

        # ── Build season table ─────────────────────────────────────────────
        # Start with roster seasons (gives team + position for every year)
        roster_szns = {}
        for _, row in player_rows.sort_values("season").iterrows():
            szn  = int(row["season"]) if pd.notna(row.get("season")) else None
            team = str(row.get("team", "") or "")
            pos  = str(row.get(pos_col, "") or "")
            if szn:
                roster_szns[szn] = {"season": szn, "team": team or None, "position": pos or None}

        # Overlay 1999+ detailed stats — collect ALL rows per season (handles trades)
        stats_szns = {}
        if not nfl_stats_df.empty:
            career_stats = nfl_stats_df[nfl_stats_df["player_display_name"] == random_name].copy()
            for _, row in career_stats.iterrows():
                def g(col, default=None):
                    v = row.get(col, default)
                    if v is None: return default
                    try:
                        if math.isnan(float(v)) or math.isinf(float(v)): return default
                    except Exception: pass
                    return v
                szn = int(row["season"]) if pd.notna(row.get("season")) else None
                if szn:
                    entry = {
                        "season":          szn,
                        "team":            g("recent_team"),
                        "position":        g("position"),
                        "passing_yards":   g("passing_yards"),
                        "passing_tds":     g("passing_tds"),
                        "interceptions":   g("passing_interceptions"),
                        "attempts":        g("attempts"),
                        "completions":     g("completions"),
                        "carries":         g("carries"),
                        "rushing_yards":   g("rushing_yards"),
                        "rushing_tds":     g("rushing_tds"),
                        "receptions":      g("receptions"),
                        "targets":         g("targets"),
                        "receiving_yards": g("receiving_yards"),
                        "receiving_tds":   g("receiving_tds"),
                    }
                    # Multiple rows per season = traded; keep as list
                    if szn in stats_szns:
                        if isinstance(stats_szns[szn], list):
                            stats_szns[szn].append(entry)
                        else:
                            stats_szns[szn] = [stats_szns[szn], entry]
                    else:
                        stats_szns[szn] = entry

        season_rows = nfl_normalize_seasons(roster_szns, stats_szns)

        def clean(v, default=None):
            """Convert NaN/Inf/None to a JSON-safe value."""
            if v is None: return default
            try:
                f = float(v)
                if math.isnan(f) or math.isinf(f): return default
                return int(f) if f == int(f) else f
            except (TypeError, ValueError):
                s = str(v)
                return None if s in ("nan", "None", "") else s

        return JSONResponse({
            "player_name": random_name,
            "position":    clean(position),
            "height":      clean(pinfo.get("height")),
            "college":     clean(pinfo.get("college")),
            "draft_pick":  clean(dinfo.get("pick")),
            "draft_round": clean(dinfo.get("round")),
            "awards": {
                "probowls": int(dinfo.get("probowls", 0) or 0),
                "allpro":   int(dinfo.get("allpro",   0) or 0),
                "hof":      bool(dinfo.get("hof", False)),
            },
            "seasons": season_rows,
        })
    except Exception as e:
        print(f"CRASH /nfl/random_player: {e}")
        return JSONResponse({"error": "An internal error occurred"}, status_code=500)

@app.get("/nfl/spin_data")
async def nfl_spin_data():
    if nfl_stats_df.empty:
        return JSONResponse({"error": "NFL data not loaded"}, status_code=500)
    try:
        df = nfl_stats_df.copy()

        # Pick a random available stat
        available = [k for k in NFL_STAT_MAP if k in df.columns]
        if not available:
            return JSONResponse({"error": "No matching stat columns"}, status_code=500)

        stat_key = random.choice(available)

        # Pick a random season with enough qualifying players
        seasons = df["season"].dropna().unique().tolist()
        for _ in range(20):
            chosen_season = random.choice(seasons)
            szn = df[(df["season"] == chosen_season) & df[stat_key].notna()].copy()

            # Minimum qualification thresholds per stat
            if stat_key in ("passing_yards", "passing_tds", "passing_interceptions", "sack_fumbles"):
                szn = szn[szn["attempts"].fillna(0) >= 100]
            elif stat_key in ("rushing_yards", "rushing_tds"):
                szn = szn[szn["carries"].fillna(0) >= 50]
            elif stat_key in ("receptions", "receiving_yards", "receiving_tds"):
                szn = szn[szn["targets"].fillna(0) >= 30]
            else:
                szn = szn[szn[stat_key].fillna(0) > 0]

            if not szn.empty:
                break
        else:
            return JSONResponse({"error": "Could not find valid season/stat"}, status_code=500)

        szn = szn.sort_values(stat_key, ascending=False)
        leader = szn.iloc[0]

        # Conference
        team = str(leader.get("recent_team", "")).upper()
        conf = NFL_TEAM_TO_CONF.get(team, "Unknown")
        pos  = str(leader.get("position", "?"))

        return JSONResponse({
            "winner": leader["player_display_name"],
            "clues": {
                "stat_name": NFL_STAT_MAP[stat_key],
                "stat_val":  str(round(float(leader[stat_key]), 0) if "." in str(leader[stat_key]) else int(leader[stat_key])),
                "season":    str(int(chosen_season)),
                "pos":       pos,
                "conf":      conf,
            },
        })
    except Exception as e:
        print(f"CRASH /nfl/spin_data: {e}")
        return JSONResponse({"error": "An internal error occurred"}, status_code=500)

# ---------------------------------------------------------------------------
# NBA spin (unchanged)
# ---------------------------------------------------------------------------

@app.get("/spin_data")
async def spin_data():
    if stats_df.empty:
        return JSONResponse({"error": "No data"}, status_code=500)
    try:
        available_stat_keys = [k for k in NBA_STAT_MAP if k in stats_df.columns]
        if not available_stat_keys:
            return JSONResponse({"error": "No matching stat columns"}, status_code=500)
        chosen_stat_key = random.choice(available_stat_keys)
        def dedup_season(df):
            counts = df.groupby("player")["player"].transform("count")
            return df[(counts == 1) | (df["team"].str.match(r"\d+TM"))]
        nba_seasons = stats_df[stats_df["lg"] == "NBA"]["season"].unique().tolist()
        for _ in range(20):
            chosen_season = random.choice(nba_seasons)
            season_df = stats_df[(stats_df["season"] == chosen_season) & (stats_df["lg"] == "NBA") & (stats_df["g"] >= 41) & stats_df[chosen_stat_key].notna()].copy()
            season_df = dedup_season(season_df)
            if not season_df.empty: break
        else:
            return JSONResponse({"error": "Could not find valid season"}, status_code=500)
        season_df   = season_df.sort_values(by=chosen_stat_key, ascending=False)
        leader_row  = season_df.iloc[0]
        stat_val    = float(leader_row[chosen_stat_key])
        team_abbrev = str(leader_row.get("team", "")).upper()
        if re.match(r"\d+TM", team_abbrev):
            pr = stats_df[(stats_df["player"] == leader_row["player"]) & (stats_df["season"] == chosen_season) & (~stats_df["team"].str.match(r"\d+TM", na=False))].copy()
            if not pr.empty:
                team_abbrev = pr.sort_values("g", ascending=False).iloc[0]["team"].upper()
        conf = TEAM_TO_CONF_NBA.get(team_abbrev, "")
        if not conf:
            for t in stats_df[(stats_df["player"] == leader_row["player"]) & (stats_df["season"] == chosen_season) & (~stats_df["team"].str.match(r"\d+TM", na=False))]["team"].tolist():
                c = TEAM_TO_CONF_NBA.get(t.upper(), "")
                if c: conf = c; team_abbrev = t.upper(); break
        return JSONResponse({
            "winner": leader_row["player"],
            "clues": {
                "stat_name": NBA_STAT_MAP[chosen_stat_key],
                "stat_val":  str(round(stat_val, 1)),
                "season":    str(chosen_season),
                "pos":       leader_row.get("pos", "N/A"),
                "conf":      conf if conf else "Unknown",
            },
        })
    except Exception as e:
        print(f"CRASH /spin_data: {e}")
        return JSONResponse({"error": "An internal error occurred"}, status_code=500)

# ---------------------------------------------------------------------------
# NFL conference map
# ---------------------------------------------------------------------------

NFL_TEAM_TO_CONF = {
    # AFC
    "BAL":"AFC","BUF":"AFC","CIN":"AFC","CLE":"AFC",
    "DEN":"AFC","HOU":"AFC","IND":"AFC","JAX":"AFC","JAC":"AFC",
    "KC":"AFC","LV":"AFC","OAK":"AFC","LAC":"AFC","SD":"AFC",
    "MIA":"AFC","NE":"AFC","NYJ":"AFC","PIT":"AFC","TEN":"AFC","OTI":"AFC",
    # NFC
    "DAL":"NFC","NYG":"NFC","PHI":"NFC","WAS":"NFC","WFT":"NFC",
    "CHI":"NFC","DET":"NFC","GB":"NFC","MIN":"NFC",
    "ATL":"NFC","CAR":"NFC","NO":"NFC","TB":"NFC",
    "ARI":"NFC","LA":"NFC","LAR":"NFC","SF":"NFC","SEA":"NFC",
}


# ---------------------------------------------------------------------------
# MLB page route
# ---------------------------------------------------------------------------

@app.get("/mlb_guess", response_class=HTMLResponse)
async def mlb_guess_page(
    request: Request,
    start_season: int = Query(1950),
    end_season: int = Query(2024),
    types: str = Query("hitters"),
):
    return templates.TemplateResponse(request, "mlb_guess.html", {
        "start_season": start_season,
        "end_season":   end_season,
        "types":        types,
    })

# ---------------------------------------------------------------------------
# MLB API routes
# ---------------------------------------------------------------------------

@app.get("/mlb/all_players")
async def mlb_all_players(types: str = Query("hitters")):
    if types == "pitchers":
        if mlb_pitching_df.empty:
            return JSONResponse({"error": "MLB data not loaded"}, status_code=500)
        players = sorted(mlb_pitching_df["player_name"].dropna().unique().tolist())
    else:
        if mlb_batting_df.empty:
            return JSONResponse({"error": "MLB data not loaded"}, status_code=500)
        players = sorted(mlb_batting_df["player_name"].dropna().unique().tolist())
    return players


@app.get("/mlb/random_player")
async def mlb_random_player(
    start_season: int = Query(1950),
    end_season:   int = Query(2024),
    types:        str = Query("hitters"),   # hitters | pitchers
):
    try:
        is_pitcher = types.lower() == "pitchers"
        df = mlb_pitching_df if is_pitcher else mlb_batting_df

        if df.empty:
            return JSONResponse({"error": "MLB data not loaded"}, status_code=500)

        pool = df[(df["yearID"] >= start_season) & (df["yearID"] <= end_season)].copy()
        if pool.empty:
            return JSONResponse({"error": "No players in this season range"}, status_code=404)

        # Qualify: hitters need 3+ seasons of 200+ AB; pitchers need 3+ seasons of 30+ IP
        if is_pitcher:
            qual = pool[pool["IP"] >= 30]
        else:
            qual = pool[pool["AB"] >= 200]

        season_counts = qual.groupby("playerID")["yearID"].nunique()
        three_plus    = season_counts[season_counts >= 3].index.tolist()
        eligible      = pool[pool["playerID"].isin(three_plus)]
        if eligible.empty:
            eligible = pool

        random_pid  = random.choice(eligible["playerID"].unique().tolist())
        random_name = eligible[eligible["playerID"] == random_pid]["player_name"].iloc[0]

        def mlb_normalize_seasons(career_df, is_pitcher):
            """
            Order multi-team seasons so the row matching the adjacent year's team
            sits closest to it — same logic as NBA/NFL.
            career_df is already filtered to one player, sorted ascending by yearID.
            """
            def g(row, col, default=None):
                v = row.get(col, default)
                if v is None: return default
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return default
                return v

            # Group rows by year
            seasons = sorted(career_df["yearID"].dropna().unique())
            szn_buckets = {}
            for szn in seasons:
                szn_rows = career_df[career_df["yearID"] == szn]
                bucket = []
                for _, row in szn_rows.iterrows():
                    if is_pitcher:
                        bucket.append({
                            "season": g(row, "yearID"), "team": g(row, "team_friendly") or g(row, "teamID"),
                            "W": g(row, "W"),  "L": g(row, "L"),  "G": g(row, "G"),
                            "GS": g(row, "GS"), "SV": g(row, "SV"), "IP": g(row, "IP"),
                            "H": g(row, "H"),  "BB": g(row, "BB"), "SO": g(row, "SO"),
                            "ERA": g(row, "ERA"), "WHIP": g(row, "WHIP"),
                        })
                    else:
                        bucket.append({
                            "season": g(row, "yearID"), "team": g(row, "team_friendly") or g(row, "teamID"),
                            "G":   g(row, "G"),   "AB":  g(row, "AB"),  "R":  g(row, "R"),
                            "H":   g(row, "H"),   "2B":  g(row, "X2B"), "3B": g(row, "X3B"),
                            "HR":  g(row, "HR"),  "RBI": g(row, "RBI"), "BB": g(row, "BB"),
                            "SO":  g(row, "SO"),  "SB":  g(row, "SB"),
                            "AVG": g(row, "AVG"), "OBP": g(row, "OBP"), "SLG": g(row, "SLG"),
                        })
                szn_buckets[int(szn)] = bucket

            result = []
            szn_list = sorted(szn_buckets.keys())  # ascending
            for i, szn in enumerate(szn_list):
                bucket = szn_buckets[szn]
                if len(bucket) == 1:
                    result.append(bucket[0])
                    continue

                teams = [r.get("team") for r in bucket]

                bottom_anchor = None
                if i > 0:
                    older_team = szn_buckets[szn_list[i - 1]][-1].get("team")
                    if older_team and older_team in teams:
                        bottom_anchor = older_team

                top_anchor = None
                if i + 1 < len(szn_list):
                    newer_team = szn_buckets[szn_list[i + 1]][0].get("team")
                    if newer_team and newer_team in teams:
                        top_anchor = newer_team

                if bottom_anchor:
                    ordered = [r for r in bucket if r.get("team") != bottom_anchor] + \
                              [r for r in bucket if r.get("team") == bottom_anchor]
                elif top_anchor:
                    ordered = [r for r in bucket if r.get("team") == top_anchor] + \
                              [r for r in bucket if r.get("team") != top_anchor]
                else:
                    ordered = bucket

                result.extend(ordered)

            # Output descending (newest first)
            ordered_buckets = {}
            for i, szn in enumerate(szn_list):
                bucket = szn_buckets[szn]
                if len(bucket) == 1:
                    ordered_buckets[szn] = bucket
                    continue
                teams = [r.get("team") for r in bucket]
                top_anchor = None
                if i + 1 < len(szn_list):
                    newer_team = szn_buckets[szn_list[i + 1]][0].get("team")
                    if newer_team and newer_team in teams:
                        top_anchor = newer_team
                bottom_anchor = None
                if i > 0:
                    older_team = szn_buckets[szn_list[i - 1]][-1].get("team")
                    if older_team and older_team in teams:
                        bottom_anchor = older_team
                if top_anchor:
                    ordered_buckets[szn] = [r for r in bucket if r.get("team") == top_anchor] + \
                                           [r for r in bucket if r.get("team") != top_anchor]
                elif bottom_anchor:
                    ordered_buckets[szn] = [r for r in bucket if r.get("team") != bottom_anchor] + \
                                           [r for r in bucket if r.get("team") == bottom_anchor]
                else:
                    ordered_buckets[szn] = bucket

            final = []
            for szn in reversed(szn_list):
                final.extend(ordered_buckets.get(szn, szn_buckets[szn]))
            return final

        # Build season rows
        career = df[df["playerID"] == random_pid].copy().sort_values("yearID")
        season_rows = mlb_normalize_seasons(career, is_pitcher)
        pid    = random_pid
        awards = mlb_awards_lkp.get(pid, {})

        # People info
        prow = mlb_people_df[mlb_people_df["playerID"] == pid]
        height   = prow.iloc[0]["height_str"] if not prow.empty else None
        bats     = prow.iloc[0]["bats"]       if not prow.empty else None
        throws   = prow.iloc[0]["throws"]     if not prow.empty else None
        position = mlb_name_map.get(pid, {}).get("position") if not is_pitcher else None

        return JSONResponse({
            "player_name": random_name,
            "height":      height,
            "bats":        str(bats) if bats and str(bats) != 'nan' else None,
            "throws":      str(throws) if throws and str(throws) != 'nan' else None,
            "position":    position,
            "is_pitcher":  is_pitcher,
            "awards": {
                "mvp":          awards.get("most valuable player", 0),
                "cy_young":     awards.get("cy young award", 0),
                "roy":          awards.get("rookie of the year", 0),
                "allstar":      awards.get("allstar", 0),
                "gold_glove":   awards.get("gold glove", 0),
                "silver_slugger": awards.get("silver slugger", 0),
                "hof":          bool(awards.get("hof", 0)),
            },
            "seasons": season_rows,
        })

    except Exception as e:
        print(f"CRASH /mlb/random_player: {e}")
        return JSONResponse({"error": "An internal error occurred"}, status_code=500)


# MLB spin stat maps
MLB_BAT_SPIN = {
    'HR':  'Home Runs',
    'RBI': 'RBIs',
    'H':   'Hits',
    'R':   'Runs Scored',
    'SB':  'Stolen Bases',
    'BB':  'Walks',
    'SO':  'Strikeouts',
    'AVG': 'Batting Average',
    'OPS': 'OPS',
}
MLB_PIT_SPIN = {
    'W':    'Wins',
    'SO':   'Strikeouts',
    'SV':   'Saves',
    'ERA':  'ERA',
    'IP':   'Innings Pitched',
    'WHIP': 'WHIP',
}
# Stats where LOWEST value wins
MLB_LOW_BEST = {'ERA', 'WHIP'}

@app.get("/mlb_spin", response_class=HTMLResponse)
async def mlb_spin_page(request: Request):
    return templates.TemplateResponse(request, "mlb_spin.html")


@app.get("/mlb/spin_data")
async def mlb_spin_data():
    if mlb_batting_df.empty and mlb_pitching_df.empty:
        return JSONResponse({"error": "MLB data not loaded"}, status_code=500)
    try:
        # Randomly pick batting or pitching category
        use_pitching = random.random() < 0.4   # 40% pitching, 60% batting
        if use_pitching and not mlb_pitching_df.empty:
            df       = mlb_pitching_df.copy()
            stat_map = MLB_PIT_SPIN
            pool_type = "pitcher"
        else:
            df       = mlb_batting_df.copy()
            stat_map = MLB_BAT_SPIN
            pool_type = "batter"

        available = [k for k in stat_map if k in df.columns]
        if not available:
            return JSONResponse({"error": "No matching stat columns"}, status_code=500)

        stat_key = random.choice(available)
        low_best = stat_key in MLB_LOW_BEST

        seasons = df['yearID'].dropna().unique().tolist()

        for _ in range(30):
            chosen_season = int(random.choice(seasons))
            szn = df[df['yearID'] == chosen_season].copy()
            szn = szn[pd.to_numeric(szn[stat_key], errors='coerce').notna()]

            # Minimum qualification thresholds
            if stat_key in ('AVG', 'OBP', 'SLG', 'OPS'):
                szn = szn[szn['AB'].fillna(0) >= 300]
            elif stat_key in ('ERA', 'WHIP'):
                szn = szn[szn['IP'].fillna(0) >= 100]
            elif stat_key == 'SV':
                szn = szn[szn['SV'].fillna(0) >= 5]
            elif stat_key == 'IP':
                szn = szn[szn['IP'].fillna(0) >= 100]
            elif pool_type == 'batter':
                szn = szn[szn['AB'].fillna(0) >= 200]
            else:
                szn = szn[szn['G'].fillna(0) >= 10]

            szn[stat_key] = pd.to_numeric(szn[stat_key], errors='coerce')
            szn = szn.dropna(subset=[stat_key])
            if not szn.empty:
                break
        else:
            return JSONResponse({"error": "Could not find valid season/stat"}, status_code=500)

        # Find leader — lowest for ERA/WHIP, highest for everything else
        if low_best:
            leader = szn.loc[szn[stat_key].idxmin()]
        else:
            leader = szn.loc[szn[stat_key].idxmax()]

        val = float(leader[stat_key])
        if stat_key in ('AVG', 'OBP', 'SLG', 'OPS'):
            val_str = f"{val:.3f}".lstrip('0') if val < 1 else f"{val:.3f}"
        elif stat_key in ('ERA', 'WHIP'):
            val_str = f"{val:.2f}"
        elif stat_key == 'IP':
            val_str = f"{val:.1f}"
        else:
            val_str = str(int(val))

        team   = str(leader.get('team_friendly') or leader.get('teamID', '?'))
        league = str(leader.get('lgID', '?'))
        pos    = 'P' if pool_type == 'pitcher' else 'Batter'

        return JSONResponse({
            "winner": leader["player_name"],
            "clues": {
                "stat_name": stat_map[stat_key],
                "stat_val":  val_str,
                "season":    str(chosen_season),
                "pos":       pos,
                "league":    league,
                "low_best":  low_best,
            },
        })
    except Exception as e:
        print(f"CRASH /mlb/spin_data: {e}")
        return JSONResponse({"error": "An internal error occurred"}, status_code=500)


