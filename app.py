"""Bos(tons) of Eats and Streets — T-reachable food for Boston students.

Run:  streamlit run app.py
Needs data/stations.csv and data/places.csv (see scripts/).
"""
import os
from datetime import datetime

import folium
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

from src.ranking import BOSTON, PLACES_CSV, cuisine_options, load_places, price_str, rank_places, surprise_pick
from src.transit import STATIONS_CSV, TransitGraph, base_route, route_color

load_dotenv()
st.set_page_config(page_title="Bos(tons) of Eats", page_icon="🍜", layout="wide")

DEFAULT_STATION = "Harvard"
BUDGETS = {"$": 1, "$$": 2, "$$$": 3, "$$$$": 4}
TYPES = {"Everything": None, "Restaurants": "restaurant", "Cafes & bakeries": "cafe"}


# ------------------------------------------------------------------ data
@st.cache_resource
def get_graph() -> TransitGraph:
    return TransitGraph.from_csv()


@st.cache_data
def get_places() -> pd.DataFrame:
    return load_places()


@st.cache_data(ttl=3600, show_spinner=False)
def last_train(station_id: str, routes: tuple[str, ...]) -> str | None:
    """Last scheduled departure today from a station on these routes, e.g. '12:41 AM'.

    Takes the earliest of the per-direction last trains (the safe answer).
    Returns None if the MBTA API can't be reached.
    """
    headers = {"x-api-key": os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else {}
    lasts = []
    try:
        for direction in (0, 1):
            r = requests.get("https://api-v3.mbta.com/schedules", headers=headers, timeout=5, params={
                "filter[stop]": station_id,
                "filter[route]": ",".join(sorted({base_route(x) for x in routes})),
                "filter[direction_id]": direction,
                "sort": "-departure_time",
                "page[limit]": 1,
                "fields[schedule]": "departure_time",
            })
            r.raise_for_status()
            data = r.json()["data"]
            if data and data[0]["attributes"]["departure_time"]:
                lasts.append(datetime.fromisoformat(data[0]["attributes"]["departure_time"]))
    except (requests.RequestException, KeyError, ValueError):
        return None
    if not lasts:
        return None
    return min(lasts).strftime("%-I:%M %p")


def check_data() -> None:
    for path, script in [(STATIONS_CSV, "fetch_stations.py"), (PLACES_CSV, "fetch_places.py")]:
        if not path.exists() or path.stat().st_size == 0:
            st.error(f"`{path.name}` is missing. Run `python scripts/{script}` first.")
            st.stop()


check_data()
graph = get_graph()
places = get_places()
stations = graph.station_table()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🍜 Bos(tons) of Eats")
    st.caption("Food you can reach on the T")

    names = stations["station_name"].tolist()
    label = dict(zip(stations["station_name"], stations["lines"]))
    origin_name = st.selectbox("📍 I'm at station", names,
                               index=names.index(DEFAULT_STATION) if DEFAULT_STATION in names else 0,
                               format_func=lambda n: f"{n}  ·  {label[n]}")
    origin_id = graph.station_id(origin_name)

    craving = st.text_input("😋 Craving", placeholder="ramen, pizza, boba…")
    cuisines = st.multiselect("Cuisine / type", cuisine_options(places))
    kind = st.radio("Show", list(TYPES), horizontal=True)
    budget = st.select_slider("💸 Max budget", options=list(BUDGETS), value="$$")
    max_trip = st.slider("⏱️ Max trip (T ride + walk), minutes", 10, 60, 40, step=5)
    min_rating = st.slider("⭐ Min rating", 0.0, 4.8, 4.0, step=0.1)

    late_night = st.toggle("🌙 Late-night mode", help="Only places open now + last train times")
    open_now = late_night or st.checkbox("Open now only")

    n_show = st.slider("📋 Results to show", 5, 50, 15, step=5)
    surprise = st.button("🎲 Surprise me", use_container_width=True)

# ------------------------------------------------------------------ rank
categories = [c.strip() for c in craving.split(",") if c.strip()]
pool = places if TYPES[kind] is None else places[places["category"] == TYPES[kind]]
trips = graph.trips_from(origin_id)
ride_min = {sid: t.minutes for sid, t in trips.items()}
now = datetime.now(BOSTON)

results = rank_places(
    pool, ride_min, budget=BUDGETS[budget], categories=categories, cuisines=cuisines,
    open_now=open_now,
    min_rating=min_rating, max_trip_min=max_trip, now=now, top_n=None,
)
# Closed places sink below open / unknown-hours ones (order within each group stays by score).
results = results.sort_values("is_open", key=lambda s: s.eq(False), kind="stable")

# Surprise pick survives reruns until the filters change.
filters_key = (origin_id, craving, tuple(cuisines), kind, budget, max_trip, min_rating, open_now)
if st.session_state.get("filters_key") != filters_key:
    st.session_state.pop("surprise", None)
    st.session_state["filters_key"] = filters_key
if surprise:
    pick = surprise_pick(results)
    st.session_state["surprise"] = None if pick is None else pick["place_id"]

top = results.head(n_show)
picked_id = st.session_state.get("surprise")
if picked_id is not None and picked_id in set(results["place_id"]):
    picked = results[results["place_id"] == picked_id].iloc[0]
    top = pd.concat([results[results["place_id"] == picked_id],
                     top[top["place_id"] != picked_id]]).head(n_show)
else:
    picked = None

# ------------------------------------------------------------------ header
st.header(f"Eats from {origin_name}")
when = now.strftime("%a %-I:%M %p")
st.caption(f"{len(results)} matches · showing top {len(top)} · {when}"
           + (" · 🌙 late-night mode" if late_night else ""))

if top.empty:
    st.warning("Nothing matches. Try a bigger budget, a longer trip, or fewer filters.")
    st.stop()

if late_night:
    lt = last_train(origin_id, tuple(r for _, r in graph.adj[origin_id]))
    st.info(f"🚇 Last train from **{origin_name}** tonight: **{lt}**" if lt else
            "🚇 Most T lines stop running around **12:30–1:00 AM**. Check the last train before you go!")


# ------------------------------------------------------------------ map
def draw_map(rows: pd.DataFrame, highlight: pd.Series) -> folium.Map:
    o_lat, o_lon = graph.coords[origin_id]
    m = folium.Map(location=[o_lat, o_lon], zoom_start=13)

    # Route to the highlighted place, colored by line.
    trip = trips[highlight["station_id"]]
    for leg in trip.legs:
        folium.PolyLine([graph.coords[s] for s in leg.path], color=route_color(leg.routes[0]),
                        weight=6, opacity=0.85, tooltip=graph.leg_label(leg)).add_to(m)
    for sid in trip.path:
        folium.CircleMarker(graph.coords[sid], radius=3, color="#333", fill=True,
                            fill_opacity=1, tooltip=graph.name[sid]).add_to(m)
    folium.PolyLine([graph.coords[highlight["station_id"]], (highlight["lat"], highlight["lon"])],
                    color="#555", weight=3, dash_array="6 6",
                    tooltip=f"Walk {highlight['walk_min']} min").add_to(m)

    folium.Marker([o_lat, o_lon], tooltip=f"You: {origin_name}",
                  icon=folium.Icon(color="black", icon="user", prefix="fa")).add_to(m)
    for i, r in enumerate(rows.itertuples(), 1):
        is_hi = r.place_id == highlight["place_id"]
        folium.Marker(
            [r.lat, r.lon],
            tooltip=f"{i}. {r.name} · ⭐{r.rating} · {int(r.total_min)} min",
            icon=folium.DivIcon(html=(
                f'<div style="background:{"#d6336c" if is_hi else "#1f6feb"};color:white;'
                f'border-radius:50%;width:26px;height:26px;text-align:center;line-height:26px;'
                f'font-weight:700;border:2px solid white;box-shadow:0 1px 4px #0006">{i}</div>'),
                icon_size=(26, 26), icon_anchor=(13, 13)),
        ).add_to(m)

    pts = [(o_lat, o_lon)] + list(zip(rows["lat"], rows["lon"]))
    m.fit_bounds(pts, padding=(30, 30))
    return m


# ------------------------------------------------------------------ cards
def open_text(r: pd.Series) -> str:
    if r["is_open"] is True:
        c = r["closes_in_min"]
        if pd.isna(c):
            return "🟢 Open 24 hours"
        return f"🟢 Open · closes in {int(c)} min" if c <= 90 else "🟢 Open now"
    if r["is_open"] is False:
        return "🔴 Closed now"
    return "⚪ Hours unknown"


def card(i: int, r: pd.Series, is_pick: bool) -> None:
    trip = trips[r["station_id"]]
    with st.container(border=True):
        title = f"### {i}. {r['name']}" + ("  🎲" if is_pick else "")
        st.markdown(title)
        rating = f"⭐ {r['rating']:.1f} ({int(r['rating_count']):,})" if pd.notna(r["rating"]) else "⭐ no rating"
        st.markdown(f"{rating} · {price_str(r['price_level'])} · {r['primary_type'] or r['category'].title()}"
                    f" · {open_text(r)}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", f"{int(r['total_min'])} min")
        c2.metric("T ride", f"{int(r['ride_min'])} min",
                  help=f"{trip.stops} stops × 2 + {trip.transfers} transfers × 5")
        c3.metric("Walk", f"{int(r['walk_min'])} min")

        steps = graph.describe(trip)
        if trip.legs:
            for step, leg in zip(steps, trip.legs):
                dot = f'<span style="color:{route_color(leg.routes[0])}">●</span>'
                st.markdown(f"{dot} {step}", unsafe_allow_html=True)
            st.markdown(f"🚶 Get off at **{r['station_name']}**, walk {int(r['walk_min'])} min "
                        f"({int(r['distance_m'])} m)")
        else:
            st.markdown(f"🚶 It's right by you, walk {int(r['walk_min'])} min ({int(r['distance_m'])} m)")

        if late_night and trip.legs:
            lt = last_train(r["station_id"], tuple(trip.legs[-1].routes))
            if lt:
                st.caption(f"🚇 Last train from {r['station_name']}: {lt}")
        if isinstance(r.get("maps_url"), str) and r["maps_url"]:
            st.link_button("Open in Google Maps", r["maps_url"])


highlight = picked if picked is not None else top.iloc[0]
map_col, list_col = st.columns([1.1, 1])
with map_col:
    if picked is not None:
        st.success(f"🎲 Surprise! Try **{picked['name']}** near {picked['station_name']}")
    st_folium(draw_map(top, highlight), height=620, use_container_width=True, returned_objects=[])
    st.caption("Route shown for the highlighted (pink) pick. Dashed line = walk.")
with list_col:
    with st.container(height=680):
        for i, (_, r) in enumerate(top.iterrows(), 1):
            card(i, r, picked is not None and r["place_id"] == picked["place_id"])
