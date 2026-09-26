from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "training" / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DUCKDB_DIR = PROCESSED / "duckdb"
CARDS = DATA / "cards"
SOURCES = DATA / "sources.json"
EVAL_SETS = REPO / "evals" / "sets"
DEMO_DIR = REPO / "web" / "public" / "data"
FIXTURES = REPO / "packages" / "sqlgen" / "fixtures"
