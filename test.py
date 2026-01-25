import sqlite3
import pandas as pd
from pathlib import Path

db_path = Path("data") / "nba_data.db"

with sqlite3.connect(db_path) as conn:
    df = pd.read_sql_query("SELECT * FROM player_per_game LIMIT 5", conn)
    print(df)
