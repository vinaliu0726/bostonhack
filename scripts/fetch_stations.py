"""Fetch every subway station on Red/Orange/Blue/Green (B/C/D/E) in route order.

For each route we take the *canonical* route patterns (direction 0, typicality 1),
e.g. Red has two: Alewife-Braintree and Alewife-Ashmont. Each pattern's
representative trip gives the stops in travel order. Platform stops are mapped to
their parent station (place-xxx) so transit.py can merge transfer stations.

Output: data/stations.csv, one row per (pattern, stop) in order:
    line, route_id, pattern_id, branch, seq, station_id, station_name, lat, lon

Run:  python scripts/fetch_stations.py
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "stations.csv"
BASE = "https://api-v3.mbta.com"
ROUTES = ["Red", "Orange", "Blue", "Green-B", "Green-C", "Green-D", "Green-E"]

load_dotenv(ROOT / ".env")
HEADERS = {"x-api-key": os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else {}


def get(path: str, params: dict | None = None) -> dict:
    """GET with a simple retry on rate limiting / transient errors."""
    for attempt in range(4):
        r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def canonical_patterns(route_id: str) -> list[dict]:
    data = get("/route_patterns", {
        "filter[route]": route_id,
        "filter[direction_id]": 0,
        "filter[canonical]": "true",
    })["data"]
    pats = [p for p in data if p["attributes"]["typicality"] == 1]
    return [{
        "pattern_id": p["id"],
        "branch": p["attributes"]["name"],
        "trip_id": p["relationships"]["representative_trip"]["data"]["id"],
    } for p in pats]


def ordered_parent_stations(trip_id: str) -> list[str]:
    """Return parent station ids (place-xxx) in travel order for a trip."""
    d = get(f"/trips/{trip_id}", {"include": "stops"})
    included = {s["id"]: s for s in d.get("included", [])}
    out = []
    for ref in d["data"]["relationships"]["stops"]["data"]:
        stop = included.get(ref["id"])
        parent = (stop or {}).get("relationships", {}).get("parent_station", {}).get("data")
        sid = parent["id"] if parent else ref["id"]
        if not out or out[-1] != sid:
            out.append(sid)
    return out


def station_info(station_ids: list[str]) -> dict[str, dict]:
    """Name + coordinates for parent stations, in one batched call."""
    info = {}
    ids = sorted(set(station_ids))
    for i in range(0, len(ids), 100):
        d = get("/stops", {
            "filter[id]": ",".join(ids[i:i + 100]),
            "fields[stop]": "name,latitude,longitude",
        })
        for s in d["data"]:
            a = s["attributes"]
            info[s["id"]] = {"station_name": a["name"], "lat": a["latitude"], "lon": a["longitude"]}
    return info


def main() -> None:
    rows = []
    for route_id in ROUTES:
        line = route_id.split("-")[0]
        pats = canonical_patterns(route_id)
        if not pats:
            print(f"WARNING: no canonical pattern for {route_id}", file=sys.stderr)
        for p in pats:
            stations = ordered_parent_stations(p["trip_id"])
            print(f"{route_id:8s} {p['branch']:40s} {len(stations):3d} stops")
            for seq, sid in enumerate(stations):
                rows.append({"line": line, "route_id": route_id, "pattern_id": p["pattern_id"],
                             "branch": p["branch"], "seq": seq, "station_id": sid})

    info = station_info([r["station_id"] for r in rows])
    df = pd.DataFrame(rows)
    df = df.join(df["station_id"].map(info).apply(pd.Series))
    missing = df["station_name"].isna().sum()
    if missing:
        print(f"WARNING: {missing} rows missing station info", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"\nSaved {len(df)} rows ({df['station_id'].nunique()} unique stations) -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
