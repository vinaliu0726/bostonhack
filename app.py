"""BiteStop — T-reachable food for Boston students.

Run:  streamlit run app.py
Needs data/stations.csv and data/places.csv (see scripts/).
Theme (white background, accent color) lives in .streamlit/config.toml.
"""
import os
from datetime import datetime
from html import escape

import folium
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

from src.ranking import BOSTON, PLACES_CSV, cuisine_options, load_places, price_str, rank_places, surprise_pick
from src.transit import STATIONS_CSV, TransitGraph, base_route, route_color, route_name

load_dotenv()
st.set_page_config(page_title="BiteStop", page_icon="🍜", layout="wide")

APP_NAME = "BiteStop"
ACCENT = "#FF6B4A"
DEFAULT_STATION = "Harvard"
BUDGETS = {"$": 1, "$$": 2, "$$$": 3, "$$$$": 4}
TYPES = {"Everything": None, "Restaurants": "restaurant", "Cafes & bakeries": "cafe"}

# ------------------------------------------------------------------ style
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Nunito:wght@400;600;700;800&display=swap');

html, body, .stApp, .stMarkdown, .stMarkdown p, label, input, textarea,
[data-baseweb="select"] div, .stButton button, [data-testid="stWidgetLabel"] p {{
    font-family: 'Nunito', sans-serif !important;
}}
h1, h2, h3, .bs-logo, .bs-name, .bs-total b, .bs-rank {{
    font-family: 'Fredoka', 'Nunito', sans-serif !important;
}}
.stApp {{ background: #FFFFFF; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: #FAFAFC; border-right: 1px solid #EEF0F5; }}

/* Force dark text even if the laptop is in dark mode and config.toml isn't picked up. */
.stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3,
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] *, [data-testid="stHeader"] * {{ color: #1F2333; }}
[data-testid="stSidebar"] svg, [data-testid="stHeader"] svg {{ fill: #4A4F63; color: #4A4F63; }}
/* Inputs, dropdowns and the dropdown menu: white box, dark text */
.stApp input, .stApp textarea, [data-baseweb="select"] > div, [data-baseweb="input"] > div,
[data-baseweb="base-input"], [data-baseweb="popover"] ul, [data-baseweb="popover"] li,
[data-baseweb="menu"] {{
    background-color: #FFFFFF !important; color: #1F2333 !important; border-color: #E3E5EC !important;
}}
[data-baseweb="popover"] li:hover {{ background-color: #FFF0EC !important; }}
.stApp input::placeholder, .stApp textarea::placeholder {{ color: #A3A8BA !important; }}
[data-baseweb="tag"] {{ background-color: {ACCENT} !important; }}
[data-baseweb="tag"] span {{ color: #FFFFFF !important; }}
.stButton button[kind="primary"], .stButton button[kind="primary"] * {{ color: #FFFFFF !important; }}
[data-testid="stAlert"] * {{ color: inherit; }}
[data-baseweb="popover"], [data-baseweb="popover"] > div, [data-baseweb="popover"] div {{
    background-color: #FFFFFF !important; color: #1F2333 !important;
}}
[data-baseweb="select"] div, [data-baseweb="select"] input {{ background-color: #FFFFFF !important; }}
[data-baseweb="select"] svg {{ fill: #4A4F63 !important; }}
/* unchecked radio / checkbox / toggle track: light instead of dark */
[data-testid="stRadio"] label > div:first-child, [data-testid="stCheckbox"] label > span:first-child {{
    background-color: #FFFFFF !important; border: 2px solid #C9CDD8 !important;
}}
[data-testid="stRadio"] input:checked + div, [data-testid="stRadio"] label:has(input:checked) > div:first-child,
[data-testid="stCheckbox"] label:has(input:checked) > span:first-child {{
    background-color: {ACCENT} !important; border-color: {ACCENT} !important;
}}
[data-testid="stToggle"] label > div:first-child {{ background-color: #D5D8E2 !important; }}
[data-testid="stToggle"] label:has(input:checked) > div:first-child {{ background-color: {ACCENT} !important; }}
.block-container {{ padding-top: 2.2rem; }}

/* sidebar logo */
.bs-logo {{ font-size: 2.2rem !important; font-weight: 700; color: {ACCENT}; line-height: 1.1; margin: 0; }}
.bs-tag  {{ color: #8A8FA3; font-size: .95rem; margin: .2rem 0 1rem; font-weight: 700; }}

/* line pills: text in the line's own color */
.bs-line {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-weight: 800;
           font-size: .82rem; margin: 2px 4px 2px 0; white-space: nowrap; }}

/* hero */
.bs-hero h1 {{ font-size: 2.4rem !important; font-weight: 600 !important; margin: 0 0 .4rem; padding: 0;
               color: #1F2333 !important; }}
.bs-hero h1 .bs-hl {{ color: {ACCENT} !important; }}
.bs-meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 1rem; }}
.bs-chip {{ display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 999px;
           background: #F4F5F9; color: #4A4F63; font-size: .85rem; font-weight: 700; }}

/* banners */
.bs-banner {{ border-radius: 16px; padding: 12px 16px; margin-bottom: 12px; font-weight: 700; }}
.bs-banner.night {{ background: #EEF0FF; color: #3B3F8F; }}
.bs-banner.surprise {{ background: #FFF0EC; color: #C2410C; }}

/* cards */
.bs-card {{ background: #FFFFFF; border: 1px solid #EEF0F5; border-radius: 20px; padding: 16px 18px;
           margin-bottom: 14px; box-shadow: 0 4px 18px rgba(31, 35, 51, .06); }}
.bs-card.pick {{ border: 2px solid {ACCENT}; box-shadow: 0 6px 22px rgba(255, 107, 74, .18); }}
.bs-top {{ display: flex; align-items: center; gap: 12px; }}
.bs-rank {{ flex: none; width: 34px; height: 34px; border-radius: 12px; background: #F4F5F9; color: #1F2333;
           display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 1.05rem; }}
.bs-card.pick .bs-rank {{ background: {ACCENT}; color: white; }}
.bs-name {{ font-size: 1.2rem; font-weight: 600; color: #1F2333; line-height: 1.2; }}
.bs-sub  {{ color: #8A8FA3; font-size: .88rem; font-weight: 600; }}
.bs-total {{ margin-left: auto; text-align: right; color: #8A8FA3; font-size: .75rem; font-weight: 700; }}
.bs-total b {{ display: block; font-size: 1.6rem; color: #1F2333; line-height: 1; }}
.bs-chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 8px; }}
.bs-chips .bs-chip {{ font-size: .8rem; padding: 3px 10px; }}
.bs-chip.open {{ background: #E9F9EF; color: #15803D; }}
.bs-chip.closed {{ background: #FDECEC; color: #B91C1C; }}
.bs-steps {{ margin: 6px 0 4px; }}
.bs-step {{ border-left: 4px solid; padding: 3px 0 3px 10px; margin: 6px 0; font-size: .92rem; color: #3A3F52; }}
.bs-step.walk {{ border-color: #D5D8E2; }}
.bs-foot {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
           margin-top: 10px; padding-top: 10px; border-top: 1px dashed #E6E8EF; color: #8A8FA3;
           font-size: .82rem; font-weight: 700; }}
.bs-foot a {{ background: {ACCENT}; color: white !important; text-decoration: none; padding: 6px 14px;
             border-radius: 999px; font-weight: 800; }}
.bs-foot a:hover {{ filter: brightness(.95); }}
.bs-hint {{ color: #8A8FA3; font-size: .82rem; margin-top: 6px; }}
</style>
""", unsafe_allow_html=True)


def line_pill(route_id: str, text: str) -> str:
    """Line name written in that line's color, on a light tint of the same color."""
    c = route_color(route_id)
    return f'<span class="bs-line" style="color:{c};background:{c}1A">{escape(text)}</span>'


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

# Routes serving each station, for the colored line pills.
station_routes = (graph.df.groupby("station_name")["route_id"]
                  .apply(lambda s: sorted(set(s), key=list(s).index)).to_dict())

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown(f'<div class="bs-logo">🍜 {APP_NAME}</div>'
                '<div class="bs-tag">Hungry? Hop on the T.</div>', unsafe_allow_html=True)

    names = stations["station_name"].tolist()
    label = dict(zip(stations["station_name"], stations["lines"]))
    origin_name = st.selectbox("📍 I'm at station", names,
                               index=names.index(DEFAULT_STATION) if DEFAULT_STATION in names else 0,
                               format_func=lambda n: f"{n}  ·  {label[n]}")
    origin_id = graph.station_id(origin_name)
    pills = []
    for r in station_routes.get(origin_name, []):
        name = route_name(r)
        if name not in [p[1] for p in pills]:
            pills.append((r, name))
    st.markdown("".join(line_pill(r, n) for r, n in pills), unsafe_allow_html=True)

    craving = st.text_input("😋 Craving", placeholder="ramen, pizza, boba…")
    cuisines = st.multiselect("🍽️ Cuisine / type", cuisine_options(places))
    kind = st.radio("Show", list(TYPES), horizontal=True)
    budget = st.select_slider("💸 Max budget", options=list(BUDGETS), value="$$")
    max_trip = st.slider("⏱️ Max trip (T ride + walk), minutes", 10, 60, 40, step=5)
    min_rating = st.slider("⭐ Min rating", 0.0, 4.8, 4.0, step=0.1)

    late_night = st.toggle("🌙 Late-night mode", help="Only places open now + last train times")
    open_now = late_night or st.checkbox("Open now only")

    n_show = st.slider("📋 Results to show", 5, 50, 15, step=5)
    surprise = st.button("🎲 Surprise me", use_container_width=True, type="primary")

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
when = now.strftime("%a %-I:%M %p")
meta = [f"🍴 {len(results)} matches", f"👀 showing {len(top)}", f"🕒 {when}"]
if late_night:
    meta.append("🌙 late-night mode")
st.markdown(
    f'<div class="bs-hero"><h1>Bites from <span class="bs-hl">{escape(origin_name)}</span></h1>'
    f'<div class="bs-meta">{"".join(line_pill(r, n) for r, n in pills)}'
    + "".join(f'<span class="bs-chip">{m}</span>' for m in meta) + "</div></div>",
    unsafe_allow_html=True)

if top.empty:
    st.warning("Nothing matches. Try a bigger budget, a longer trip, or fewer filters.")
    st.stop()

if late_night:
    lt = last_train(origin_id, tuple(r for _, r in graph.adj[origin_id]))
    msg = (f"🚇 Last train from <b>{escape(origin_name)}</b> tonight: <b>{lt}</b>" if lt else
           "🚇 Most T lines stop running around <b>12:30–1:00 AM</b>. Check the last train before you go!")
    st.markdown(f'<div class="bs-banner night">{msg}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ map
def draw_map(rows: pd.DataFrame, highlight: pd.Series) -> folium.Map:
    o_lat, o_lon = graph.coords[origin_id]
    m = folium.Map(location=[o_lat, o_lon], zoom_start=13)

    # Route to the highlighted place, colored by line.
    trip = trips[highlight["station_id"]]
    for leg in trip.legs:
        folium.PolyLine([graph.coords[s] for s in leg.path], color=route_color(leg.routes[0]),
                        weight=7, opacity=0.9, tooltip=graph.leg_label(leg)).add_to(m)
    for sid in trip.path:
        folium.CircleMarker(graph.coords[sid], radius=4, color="white", weight=2, fill=True,
                            fill_color="#1F2333", fill_opacity=1, tooltip=graph.name[sid]).add_to(m)
    folium.PolyLine([graph.coords[highlight["station_id"]], (highlight["lat"], highlight["lon"])],
                    color="#8A8FA3", weight=3, dash_array="6 6",
                    tooltip=f"Walk {highlight['walk_min']} min").add_to(m)

    folium.Marker([o_lat, o_lon], tooltip=f"You: {origin_name}",
                  icon=folium.Icon(color="black", icon="user", prefix="fa")).add_to(m)
    for i, r in enumerate(rows.itertuples(), 1):
        is_hi = r.place_id == highlight["place_id"]
        folium.Marker(
            [r.lat, r.lon],
            tooltip=f"{i}. {r.name} · ⭐{r.rating} · {int(r.total_min)} min",
            icon=folium.DivIcon(html=(
                f'<div style="background:{ACCENT if is_hi else "#1F2333"};color:white;'
                f'border-radius:10px;width:28px;height:28px;text-align:center;line-height:28px;'
                f'font-family:Nunito,sans-serif;font-weight:800;border:2px solid white;'
                f'box-shadow:0 2px 8px #0004">{i}</div>'),
                icon_size=(28, 28), icon_anchor=(14, 14)),
        ).add_to(m)

    pts = [(o_lat, o_lon)] + list(zip(rows["lat"], rows["lon"]))
    m.fit_bounds(pts, padding=(30, 30))
    return m


# ------------------------------------------------------------------ cards
def open_chip(r: pd.Series) -> str:
    if r["is_open"] is True:
        c = r["closes_in_min"]
        if pd.isna(c):
            text = "● Open 24 hours"
        else:
            text = f"● Open · closes in {int(c)} min" if c <= 90 else "● Open now"
        return f'<span class="bs-chip open">{text}</span>'
    if r["is_open"] is False:
        return '<span class="bs-chip closed">● Closed now</span>'
    return '<span class="bs-chip">● Hours unknown</span>'


def card_html(i: int, r: pd.Series, is_pick: bool) -> str:
    trip = trips[r["station_id"]]
    kind_text = r["primary_type"] or r["category"].title()
    sub = f"{escape(kind_text)} · {price_str(r['price_level'])}"
    rating = (f"⭐ {r['rating']:.1f} <span style='opacity:.6'>({int(r['rating_count']):,})</span>"
              if pd.notna(r["rating"]) else "⭐ no rating")

    steps = []
    for j, leg in enumerate(trip.legs):
        c = route_color(leg.routes[0])
        verb = "Take" if j == 0 else "Transfer to"
        s = "stop" if leg.stops == 1 else "stops"
        steps.append(
            f'<div class="bs-step" style="border-color:{c}">{verb} '
            f'{line_pill(leg.routes[0], graph.leg_label(leg))} toward {escape(leg.toward)} · '
            f'{leg.stops} {s} → <b style="color:{c}">{escape(graph.name[leg.to_id])}</b></div>')
    if trip.legs:
        steps.append(f'<div class="bs-step walk">🚶 Get off at <b>{escape(r["station_name"])}</b>, '
                     f'walk {int(r["walk_min"])} min ({int(r["distance_m"])} m)</div>')
    else:
        steps.append(f'<div class="bs-step walk">🚶 Right by you, walk {int(r["walk_min"])} min '
                     f'({int(r["distance_m"])} m)</div>')

    x = "transfer" if trip.transfers == 1 else "transfers"
    foot = f"🚇 {int(r['ride_min'])} min ride · {trip.stops} stops · {trip.transfers} {x}"
    if late_night and trip.legs:
        lt = last_train(r["station_id"], tuple(trip.legs[-1].routes))
        if lt:
            foot += f" · last train {lt}"
    link = (f'<a href="{escape(r["maps_url"])}" target="_blank">Google Maps ↗</a>'
            if isinstance(r.get("maps_url"), str) and r["maps_url"] else "")

    return (
        f'<div class="bs-card{" pick" if is_pick else ""}">'
        f'<div class="bs-top"><div class="bs-rank">{"🎲" if is_pick else i}</div>'
        f'<div><div class="bs-name">{escape(r["name"])}</div><div class="bs-sub">{sub}</div></div>'
        f'<div class="bs-total"><b>{int(r["total_min"])}</b>min total</div></div>'
        f'<div class="bs-chips"><span class="bs-chip">{rating}</span>{open_chip(r)}'
        f'<span class="bs-chip">🚶 {int(r["walk_min"])} min walk</span></div>'
        f'<div class="bs-steps">{"".join(steps)}</div>'
        f'<div class="bs-foot"><span>{foot}</span>{link}</div>'
        f'</div>'
    )


highlight = picked if picked is not None else top.iloc[0]
map_col, list_col = st.columns([1.1, 1], gap="large")
with map_col:
    if picked is not None:
        st.markdown(f'<div class="bs-banner surprise">🎲 Surprise! Try <b>{escape(picked["name"])}</b> '
                    f'near {escape(picked["station_name"])}</div>', unsafe_allow_html=True)
    st_folium(draw_map(top, highlight), height=620, use_container_width=True, returned_objects=[])
    st.markdown('<div class="bs-hint">Route shown for the highlighted pick · dashed line = walk</div>',
                unsafe_allow_html=True)
with list_col:
    with st.container(height=680, border=False):
        st.markdown("".join(
            card_html(i, r, picked is not None and r["place_id"] == picked["place_id"])
            for i, (_, r) in enumerate(top.iterrows(), 1)), unsafe_allow_html=True)
