"""Fetch restaurants and cafes within 500 m of a set of popular T stations.

Uses Google Places API (New) "searchNearby". Station coordinates come from
data/stations.csv (run scripts/fetch_stations.py first), so station_id here
matches the ids transit.py uses.

searchNearby returns at most 20 results per call, so for each station we make
two calls (restaurants, then cafes/bakeries) ranked by popularity.

Output: data/places.csv, one row per (station, place). A place near two
stations appears twice, so ranking can pick whichever station is better:
    station_id, station_name, place_id, name, category, primary_type, types,
    rating, rating_count, price_level, lat, lon, address, distance_m, walk_min,
    hours_json, hours_text, maps_url

price_level: 0=free, 1=$, 2=$$, 3=$$$, 4=$$$$, blank=unknown.
hours_json: regularOpeningHours.periods as JSON (for "open now" in ranking.py).

Run:  python scripts/fetch_places.py
      python scripts/fetch_places.py --all                  # every subway station (~236 calls)
      python scripts/fetch_places.py "Museum of Fine Arts" "Fenway"
          -> fetch only these stations and ADD them to the existing places.csv
      python scripts/fetch_places.py --deep "Harvard Avenue" "Allston Street"
          -> also one search per popular cuisine (12 calls/station instead of 2),
             finds many more Korean/Chinese/... places in dense areas. Adds to file.
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# Google's cafe/restaurant search also returns museums, hotels... that merely *contain*
# a cafe. Keep a place only if its main type sounds like food. (Same list as src/ranking.py.)
FOOD_WORDS = (
    "restaurant", "cafe", "café", "coffee", "bakery", "tea", "dessert", "ice cream",
    "juice", "donut", "bagel", "sandwich", "deli", "diner", "food", "pizza", "steak",
    "bar", "pub", "grill", "bistro", "brunch", "breakfast", "confection", "chocolate",
    "candy", "acai", "boba", "noodle", "ramen", "sushi", "taco", "burrito", "meal",
    "cafeteria", "patisserie", "creperie", "buffet", "eatery", "snack", "kitchen",
    "bubble", "yogurt", "dumpling", "hot pot", "barbecue", "bbq", "chicken", "burger",
)
NOT_FOOD_WORDS = ("barber", "supply", "pet ", "grocery", "supermarket", "museum", "hotel")


def is_food(primary_type: str) -> bool:
    t = primary_type.lower()
    if not t:
        return True
    return any(w in t for w in FOOD_WORDS) and not any(w in t for w in NOT_FOOD_WORDS)

ROOT = Path(__file__).resolve().parent.parent
STATIONS = ROOT / "data" / "stations.csv"
OUT = ROOT / "data" / "places.csv"
URL = "https://places.googleapis.com/v1/places:searchNearby"
RADIUS_M = 500.0
WALK_M_PER_MIN = 80.0   # ~4.8 km/h
DETOUR = 1.3            # streets aren't straight lines

# Popular stations for college students (names must match data/stations.csv).
DEFAULT_STATIONS = [
    # Cambridge / Somerville
    "Harvard", "Central", "Kendall/MIT", "Davis", "Porter", "Alewife",
    "Union Square", "Lechmere", "Medford/Tufts", "Ball Square", "Assembly", "Sullivan Square",
    # Downtown
    "Park Street", "Downtown Crossing", "Chinatown", "Haymarket", "Government Center",
    "State", "South Station", "North Station", "Aquarium", "Boylston", "Arlington",
    # Back Bay / Fenway / Longwood
    "Copley", "Back Bay", "Prudential", "Hynes Convention Center", "Symphony",
    "Massachusetts Avenue", "Kenmore", "Fenway", "Longwood Medical Area",
    "Museum of Fine Arts", "Northeastern University", "Brigham Circle", "Ruggles",
    # BU / Allston / Brookline
    "Boston University East", "Boston University Central", "Babcock Street",
    "Harvard Avenue", "Packard's Corner", "Allston Street", "Griggs Street", "Warren Street", "Coolidge Corner", "Brookline Village",
    "Boston College",
    # South / East
    "JFK/UMass", "Jackson Square", "Forest Hills", "Maverick", "Airport",
]
# (category label, includedTypes) — one searchNearby call each.
SEARCHES = [
    ("restaurant", ["restaurant"]),
    ("cafe", ["cafe", "coffee_shop", "bakery"]),
]
# Extra searches for --deep: Google caps each search at 20, so a broad "restaurant"
# search misses most places in dense areas. One search per cuisine digs deeper.
DEEP_SEARCHES = [("restaurant", [t]) for t in [
    "korean_restaurant", "chinese_restaurant", "japanese_restaurant", "ramen_restaurant",
    "sushi_restaurant", "thai_restaurant", "vietnamese_restaurant", "indian_restaurant",
    "mexican_restaurant", "pizza_restaurant",
]]

FIELDS = ",".join("places." + f for f in [
    "id", "displayName", "primaryType", "primaryTypeDisplayName", "types",
    "rating", "userRatingCount", "priceLevel", "location", "shortFormattedAddress",
    "regularOpeningHours", "googleMapsUri", "businessStatus",
])

PRICE = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

load_dotenv(ROOT / ".env")
API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_nearby(lat: float, lon: float, types: list[str]) -> list[dict]:
    body = {
        "includedTypes": types,
        "maxResultCount": 20,
        "rankPreference": "POPULARITY",
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": RADIUS_M}
        },
    }
    headers = {"X-Goog-Api-Key": API_KEY, "X-Goog-FieldMask": FIELDS}
    for attempt in range(4):
        r = requests.post(URL, json=body, headers=headers, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if not r.ok:
            # Google puts the useful message (API not enabled, bad key...) in the body.
            sys.exit(f"Places API error {r.status_code}: {r.text[:500]}")
        return r.json().get("places", [])
    sys.exit(f"Places API kept failing ({r.status_code}): {r.text[:300]}")


def to_row(p: dict, station: pd.Series, category: str) -> dict | None:
    if p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
        return None
    if not is_food(p.get("primaryTypeDisplayName", {}).get("text", "")):
        return None                                  # e.g. a museum that has a cafe
    loc = p.get("location", {})
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if lat is None or lon is None:
        return None
    dist = haversine_m(station.lat, station.lon, lat, lon)
    hours = p.get("regularOpeningHours", {})
    return {
        "station_id": station.station_id,
        "station_name": station.station_name,
        "place_id": p["id"],
        "name": p.get("displayName", {}).get("text", ""),
        "category": category,
        "primary_type": p.get("primaryTypeDisplayName", {}).get("text")
                        or p.get("primaryType", "").replace("_", " ").title(),
        "types": "|".join(p.get("types", [])),
        "rating": p.get("rating"),
        "rating_count": p.get("userRatingCount", 0),
        "price_level": PRICE.get(p.get("priceLevel")),
        "lat": lat,
        "lon": lon,
        "address": p.get("shortFormattedAddress", ""),
        "distance_m": round(dist),
        "walk_min": max(1, round(dist * DETOUR / WALK_M_PER_MIN)),
        "hours_json": json.dumps(hours["periods"]) if hours.get("periods") else "",
        "hours_text": " | ".join(hours.get("weekdayDescriptions", [])),
        "maps_url": p.get("googleMapsUri", ""),
    }


def load_stations(names: list[str]) -> pd.DataFrame:
    if not STATIONS.exists():
        sys.exit(f"{STATIONS.relative_to(ROOT)} not found. Run scripts/fetch_stations.py first.")
    st = (pd.read_csv(STATIONS)
          .drop_duplicates("station_id")[["station_id", "station_name", "lat", "lon"]])
    picked = st[st["station_name"].isin(names)]
    missing = set(names) - set(picked["station_name"])
    if missing:
        print(f"WARNING: not in stations.csv, skipped: {sorted(missing)}", file=sys.stderr)
    return picked


def main() -> None:
    if not API_KEY:
        sys.exit("GOOGLE_PLACES_API_KEY is not set. Copy .env.example to .env and fill it in.")

    args = sys.argv[1:]
    deep = "--deep" in args
    use_all = "--all" in args
    names = [a for a in args if not a.startswith("--")]
    add_mode = bool(names) or deep          # partial fetch -> add to existing file
    if use_all:
        names = pd.read_csv(STATIONS)["station_name"].unique().tolist()
    elif not names:
        names = DEFAULT_STATIONS
    stations = load_stations(names)
    searches = SEARCHES + (DEEP_SEARCHES if deep else [])
    print(f"Fetching {len(stations)} stations ({len(searches) * len(stations)} Google calls)...\n")

    rows = []
    for st in stations.itertuples(index=False):
        n_before = len(rows)
        for category, types in searches:
            for p in search_nearby(st.lat, st.lon, types):
                row = to_row(p, st, category)
                if row:
                    rows.append(row)
        print(f"{st.station_name:28s} {len(rows) - n_before:3d} places")

    if not rows:
        sys.exit("No places returned — nothing saved.")

    df = (pd.DataFrame(rows)
          .drop_duplicates(["station_id", "place_id"])  # cafe+restaurant overlap
          .sort_values(["station_name", "rating_count"], ascending=[True, False]))

    if add_mode and OUT.exists() and OUT.stat().st_size > 0:
        old = pd.read_csv(OUT, dtype={"hours_json": str, "hours_text": str})
        old = old[~old["station_id"].isin(df["station_id"])]   # refresh these stations
        df = pd.concat([old, df], ignore_index=True)
        print(f"Added to existing file ({len(old)} rows kept from other stations)")
    df["price_level"] = df["price_level"].astype("Int64")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"\nSaved {len(df)} rows ({df['place_id'].nunique()} unique places, "
          f"{df['station_id'].nunique()} stations) -> {OUT.relative_to(ROOT)}")
    print(f"Missing price level: {df['price_level'].isna().sum()}  |  "
          f"missing hours: {(df['hours_json'] == '').sum()}")


if __name__ == "__main__":
    main()
