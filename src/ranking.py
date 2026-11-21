"""Filter and score places from data/places.csv.

Main entry point:
    rank_places(places, ride_min, budget=2, categories=["Pizza"], open_now=True)

`ride_min` maps station_id -> minutes on the T from the user's station
(transit.py computes it: stops * 2 + transfers * 5). Pass None before
transit.py exists and every station counts as 0 ride minutes.

A place near several stations has several rows in places.csv; we keep the one
with the shortest total trip (ride + walk).

Score (0-100) = 50% rating + 35% travel time + 15% price.
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PLACES_CSV = ROOT / "data" / "places.csv"
BOSTON = ZoneInfo("America/New_York")

W_RATING, W_TIME, W_PRICE = 0.50, 0.35, 0.15
MAX_TRIP_MIN = 60        # trips this long (or longer) get 0 time score
PRIOR_RATING = 4.0       # Bayesian average: few reviews -> pulled toward 4.0
PRIOR_COUNT = 50
WEEK_MIN = 7 * 24 * 60


# Google's cafe/restaurant search also returns museums, hotels, stores... that merely
# *contain* a cafe. Keep a place only if its main type sounds like food.
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
        return True                                   # unknown type -> keep
    return any(w in t for w in FOOD_WORDS) and not any(w in t for w in NOT_FOOD_WORDS)


def load_places(path: Path = PLACES_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"hours_json": str, "hours_text": str})
    df["price_level"] = df["price_level"].astype("Int64")
    df["rating_count"] = df["rating_count"].fillna(0).astype(int)
    df[["hours_json", "hours_text", "primary_type"]] = (
        df[["hours_json", "hours_text", "primary_type"]].fillna(""))
    return df[df["primary_type"].map(is_food)].reset_index(drop=True)


def cuisine_options(places: pd.DataFrame) -> list[str]:
    """Distinct primary types (e.g. 'Pizza Restaurant', 'Coffee Shop') for the sidebar."""
    return sorted(t for t in places["primary_type"].unique() if t)


# ---------------------------------------------------------------- open now
def _week_min(day: int, hour: int, minute: int) -> int:
    """Minutes since Sunday 00:00 (Google uses day 0 = Sunday)."""
    return day * 1440 + hour * 60 + minute


def open_status(hours_json: str, now: datetime) -> tuple[bool | None, int | None]:
    """(is_open, minutes_until_close) at `now`. (None, None) if hours unknown.

    minutes_until_close is None when open 24/7.
    """
    if not hours_json:
        return None, None
    try:
        periods = json.loads(hours_json)
    except json.JSONDecodeError:
        return None, None
    now_w = _week_min((now.weekday() + 1) % 7, now.hour, now.minute)  # Mon=0 -> Sun=0
    for p in periods:
        o = p.get("open")
        c = p.get("close")
        if not o:
            continue
        if not c:                                   # open 24/7
            return True, None
        start = _week_min(o["day"], o.get("hour", 0), o.get("minute", 0))
        end = _week_min(c["day"], c.get("hour", 0), c.get("minute", 0))
        if end <= start:                            # wraps past Saturday night
            end += WEEK_MIN
        for t in (now_w, now_w + WEEK_MIN):         # handle the week wrap
            if start <= t < end:
                return True, end - t
    return False, None


# ---------------------------------------------------------------- ranking
def rank_places(
    places: pd.DataFrame,
    ride_min: dict[str, float] | None = None,
    budget: int | None = None,
    categories: list[str] | None = None,
    cuisines: list[str] | None = None,
    open_now: bool = False,
    min_rating: float = 0.0,
    max_trip_min: float | None = None,
    include_unknown_price: bool = True,
    now: datetime | None = None,
    top_n: int | None = 10,
) -> pd.DataFrame:
    """Filter + score places. Returns best first, one row per place.

    budget:      max price level (1=$ .. 4=$$$$). None = any.
    categories:  craving keywords matched (case-insensitive) against name, category,
                 primary_type and types, e.g. ["pizza", "boba"]. Any keyword matching keeps it.
    cuisines:    exact primary_type values from cuisine_options(), e.g. ["Korean Restaurant"].
                 Combined with categories using AND (must be one of these cuisines AND match a keyword).
    open_now:    keep only places open right now (unknown hours are dropped).
    """
    now = now or datetime.now(BOSTON)
    df = places.copy()

    # Travel time: T ride to the place's station + walk from that station.
    if ride_min is None:
        df["ride_min"] = 0.0
    else:
        df["ride_min"] = df["station_id"].map(ride_min)
        df = df[df["ride_min"].notna()]             # station unreachable / unknown
    df["total_min"] = df["ride_min"] + df["walk_min"]

    # Same place near several stations -> keep the fastest way there.
    df = df.sort_values("total_min").drop_duplicates("place_id", keep="first")

    # ---- filters
    if budget is not None:
        ok = df["price_level"] <= budget
        if include_unknown_price:
            ok = ok | df["price_level"].isna()
        df = df[ok.fillna(False).astype(bool)]

    if categories:
        text = (df["name"].fillna("") + " " + df["category"] + " " + df["primary_type"] + " "
                + df["types"].fillna("")).str.lower().str.replace("_", " ")
        mask = np.zeros(len(df), dtype=bool)
        for c in categories:
            mask |= text.str.contains(c.lower().strip(), regex=False).to_numpy()
        df = df[mask]

    if cuisines:
        df = df[df["primary_type"].isin(cuisines)]

    if min_rating:
        df = df[df["rating"].fillna(0) >= min_rating]

    if max_trip_min is not None:
        df = df[df["total_min"] <= max_trip_min]

    status = df["hours_json"].apply(lambda h: open_status(h, now))
    df["is_open"] = status.str[0]
    df["closes_in_min"] = status.str[1]
    if open_now:
        df = df[df["is_open"] == True]  # noqa: E712  (None/False both dropped)

    if df.empty:
        return df.assign(score=pd.Series(dtype=float))

    # ---- score
    r = df["rating"].fillna(PRIOR_RATING)
    n = df["rating_count"]
    adj = (r * n + PRIOR_RATING * PRIOR_COUNT) / (n + PRIOR_COUNT)
    rating_s = ((adj - 3.0) / 2.0).clip(0, 1)                 # 3.0 -> 0, 5.0 -> 1
    time_s = (1 - df["total_min"] / MAX_TRIP_MIN).clip(0, 1)
    price_s = ((4 - df["price_level"].astype(float)) / 3).fillna(0.5).clip(0, 1)

    df["score"] = (100 * (W_RATING * rating_s + W_TIME * time_s + W_PRICE * price_s)).round(1)
    df = df.sort_values(["score", "rating_count"], ascending=False)
    return df.head(top_n) if top_n else df


def surprise_pick(ranked: pd.DataFrame, pool: int = 10, seed: int | None = None) -> pd.Series | None:
    """Random pick from the top `pool` results, weighted toward higher scores."""
    if ranked.empty:
        return None
    top = ranked.head(pool)
    w = top["score"].clip(lower=1) ** 2
    return top.sample(1, weights=w, random_state=seed).iloc[0]


def price_str(level) -> str:
    """1 -> '$', NA -> '?' (for display)."""
    return "?" if pd.isna(level) else ("Free" if level == 0 else "$" * int(level))


if __name__ == "__main__":
    # Quick check: python -m src.ranking
    p = load_places()
    print(f"{len(p)} rows, {p['place_id'].nunique()} places")
    top = rank_places(p, budget=2, open_now=False, top_n=10)
    cols = ["name", "station_name", "primary_type", "rating", "rating_count",
            "price_level", "walk_min", "total_min", "is_open", "score"]
    print(top[cols].to_string(index=False))
    pick = surprise_pick(top)
    if pick is not None:
        print(f"\nSurprise: {pick['name']} near {pick['station_name']}")
