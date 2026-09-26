"""Build the 3 demo DuckDB files shipped with the web app (web/public/data/).

- chinook: the Chinook music store (MIT), converted from its SQLite build.
- penguins: Palmer penguins (CC0), from the palmerpenguins CSV.
- world_bank: World Development Indicators (CC BY 4.0) for 2000–2023 through the
  World Bank API v2. The API is live data, so the committed file is the pinned copy;
  `--refresh-world-bank` refetches it and records the retrieval date in sources.json.
"""

import argparse
import datetime as dt
import json
import urllib.request
from pathlib import Path

import duckdb

from pocketsql.data import paths
from pocketsql.data.convert import load_sqlite, quote_literal
from pocketsql.data.download import fetch

MAX_BYTES = 2 * 1024 * 1024
BLOCK_SIZE = 16 * 1024
API = "https://api.worldbank.org/v2/"
YEARS = (2000, 2023)
# column name -> (WDI indicator code, decimals kept)
INDICATORS = {
    "population": ("SP.POP.TOTL", 0),
    "gdp_usd": ("NY.GDP.MKTP.CD", 0),
    "gdp_per_capita_usd": ("NY.GDP.PCAP.CD", 2),
    "life_expectancy_years": ("SP.DYN.LE00.IN", 2),
    "fertility_rate": ("SP.DYN.TFRT.IN", 2),
    "urban_population_pct": ("SP.URB.TOTL.IN.ZS", 2),
    "internet_users_pct": ("IT.NET.USER.ZS", 2),
    "unemployment_pct": ("SL.UEM.TOTL.ZS", 2),
}


def _get(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "pocketsql"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        meta, rows = json.load(resp)
    if meta["pages"] != 1:
        raise SystemExit(f"unexpected pagination for {url}: {meta}")
    return rows


def build_chinook() -> None:
    notes = load_sqlite(fetch("chinook"), paths.DEMO_DIR / "chinook.duckdb")
    print("chinook:", notes or "no fallbacks")


def build_penguins() -> None:
    dest = paths.DEMO_DIR / "penguins.duckdb"
    dest.unlink(missing_ok=True)
    with duckdb.connect(str(dest)) as con:
        con.execute(
            "CREATE TABLE penguins AS SELECT * FROM read_csv("
            f"{quote_literal(str(fetch('penguins')))}, nullstr = 'NA', header = true)"
        )


def build_world_bank() -> None:
    countries = [
        c
        for c in _get(f"{API}country?format=json&per_page=400")
        if c["region"]["id"] != "NA"
    ]
    values: dict[tuple[str, int], dict[str, float | None]] = {}
    for col, (code, _) in INDICATORS.items():
        url = (
            f"{API}country/all/indicator/{code}?format=json&per_page=20000"
            f"&date={YEARS[0]}:{YEARS[1]}"
        )
        for r in _get(url):
            key = (r["countryiso3code"], int(r["date"]))
            values.setdefault(key, {})[col] = r["value"]
    iso3 = {c["id"] for c in countries}
    dest = paths.DEMO_DIR / "world_bank.duckdb"
    dest.unlink(missing_ok=True)
    with duckdb.connect(str(dest)) as con:
        con.execute(
            "CREATE TABLE countries (iso3 VARCHAR, name VARCHAR, region VARCHAR, "
            "income_group VARCHAR, capital_city VARCHAR)"
        )
        con.executemany(
            "INSERT INTO countries VALUES (?, ?, ?, ?, ?)",
            [
                [
                    c["id"],
                    c["name"].strip(),
                    c["region"]["value"].strip(),
                    c["incomeLevel"]["value"].strip(),
                    c["capitalCity"].strip() or None,
                ]
                for c in sorted(countries, key=lambda c: c["id"])
            ],
        )
        cols = ", ".join(
            f"{c} {'BIGINT' if d == 0 else 'DOUBLE'}"
            for c, (_, d) in INDICATORS.items()
        )
        con.execute(f"CREATE TABLE country_stats (iso3 VARCHAR, year BIGINT, {cols})")
        rows = []
        for (code, year), v in sorted(values.items()):
            if code not in iso3 or all(x is None for x in v.values()):
                continue
            rows.append(
                [code, year]
                + [
                    None if v.get(c) is None else round(v[c], d) if d else round(v[c])
                    for c, (_, d) in INDICATORS.items()
                ]
            )
        marks = ", ".join("?" for _ in range(2 + len(INDICATORS)))
        con.executemany(f"INSERT INTO country_stats VALUES ({marks})", rows)
    sources = json.loads(paths.SOURCES.read_text(encoding="utf-8"))
    sources["world_bank"]["retrieved"] = dt.date.today().isoformat()
    sources["world_bank"]["indicators"] = {
        c: code for c, (code, _) in INDICATORS.items()
    }
    paths.SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(f"world_bank: {len(countries)} countries, {len(rows)} country-years")


def compact(path: Path) -> None:
    """Rewrite with 16 KiB blocks: DuckDB's default 256 KiB blocks make even a tiny
    database 0.5 MB. Readable by DuckDB >= 1.2 (and so by current DuckDB-WASM)."""
    tmp = path.with_suffix(".tmp")
    path.replace(tmp)
    with duckdb.connect() as con:
        con.execute(f"ATTACH {quote_literal(str(tmp))} AS s (READ_ONLY)")
        con.execute(f"ATTACH {quote_literal(str(path))} AS d (BLOCK_SIZE {BLOCK_SIZE})")
        con.execute("COPY FROM DATABASE s TO d")
    tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.data.demo")
    parser.add_argument("--refresh-world-bank", action="store_true")
    args = parser.parse_args(argv)
    paths.DEMO_DIR.mkdir(parents=True, exist_ok=True)
    build_chinook()
    compact(paths.DEMO_DIR / "chinook.duckdb")
    build_penguins()
    compact(paths.DEMO_DIR / "penguins.duckdb")
    if args.refresh_world_bank or not (paths.DEMO_DIR / "world_bank.duckdb").exists():
        build_world_bank()
        compact(paths.DEMO_DIR / "world_bank.duckdb")
    too_big = []
    for f in sorted(paths.DEMO_DIR.glob("*.duckdb")):
        size = f.stat().st_size
        print(f"{f.name}: {size / 1024:.0f} KiB")
        if size > MAX_BYTES:
            too_big.append(f.name)
    if too_big:
        raise SystemExit(f"demo files over 2 MB: {too_big}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
