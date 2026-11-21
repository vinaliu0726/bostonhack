# bostonhack

🍜 BiteStop
Hungry? Hop on the T.

BiteStop helps Boston college students find food they can actually get to by subway. Tell it what you're craving, your budget, and which T station you're at, and it recommends restaurants and cafés with step-by-step directions: which line to take, where to transfer, which stop to get off at, and how many minutes to walk.

Built at BostonHacks for the Bos(tons) of Eats and Streets track.

BiteStop screenshot

✨ Features
Craving + budget + station search. Type what you want ("ramen, boba"), pick cuisines, set a max price ($–$$$$), a max trip time and a minimum rating.
T directions on every card. For example: Take the Red Line toward Ashmont/Braintree, 4 stops → Park Street. Transfer to the Green Line B/C/D, 5 stops → Kenmore. Walk 3 min. Each line is shown in its official MBTA color.
Smart ranking. Places are scored on rating (adjusted for review count), total travel time and price.
Route map. An interactive map shows the results and draws the subway route to the top pick, colored by line, with a dashed walking leg.
🌙 Late-night mode. Shows only places that are open right now, plus the last train time from live MBTA schedules.
🎲 Surprise me. Can't decide? Get a random pick from the top results, weighted toward better scores.
🧠 How it works
MBTA V3 API ──► scripts/fetch_stations.py ──► data/stations.csv ──► src/transit.py ─┐
                                                                                    ├─► src/ranking.py ──► app.py
Google Places API ──► scripts/fetch_places.py ──► data/places.csv ──────────────────┘
Stations (scripts/fetch_stations.py): fetches every Red, Orange, Blue and Green (B/C/D/E) station in route order from the MBTA V3 API.
Places (scripts/fetch_places.py): uses Google Places (New) Nearby Search to find restaurants and cafés within 500 m of student-heavy stations. It drops non-food places such as museums that merely contain a café.
Transit graph (src/transit.py): builds a graph where transfer stations (e.g. Park Street) are a single node. A weighted BFS over (station, line) states finds the trip with the fewest minutes, counting transfers properly. This includes changing between Green Line branches, or between the Ashmont and Braintree Red Line branches at JFK/UMass.
Ranking (src/ranking.py): filters by budget, cuisine, craving, rating, trip time and open-now, then scores each place.
App (app.py): a Streamlit UI with a sidebar of filters, recommendation cards and a Folium map.
Travel time estimate
total minutes = stops × 2 + transfers × 5 + walking minutes
walking minutes = straight-line distance × 1.3 ÷ 80 m/min
Score (0–100)
Weight	Component	Notes
50%	Rating	Bayesian average, so a 4.8★ with 5 reviews doesn't beat a 4.6★ with 900
35%	Travel time	0 min = full score, 60+ min = 0
15%	Price	Cheaper scores higher; unknown price counts as neutral
🚀 Run it locally
Requirements: Python 3.10+

git clone https://github.com/vinaliu0726/bostonhack.git
cd bostonhack
pip install -r requirements.txt
streamlit run app.py
Then open http://localhost:8501.

The repo includes data/stations.csv and data/places.csv, so no API keys are needed to run the app. The only live call is the optional last-train lookup in late-night mode. It uses the public MBTA API and falls back to a general note if that call fails.

Refreshing the data (optional)
You only need API keys to re-fetch data.

Copy .env.example to .env and fill it in. .env is gitignored, so never commit keys.
MBTA_API_KEY=...            # optional, raises the MBTA rate limit
GOOGLE_PLACES_API_KEY=...   # needs "Places API (New)" enabled
Fetch the data:
python scripts/fetch_stations.py                      # all subway stations
python scripts/fetch_places.py                        # ~50 student-heavy stations
python scripts/fetch_places.py "Museum of Fine Arts"  # add specific stations
python scripts/fetch_places.py --deep "Harvard Avenue" "Allston Street"
                                                      # + one search per cuisine (more results)
📁 Project structure
bostonhack/
├── app.py                     # Streamlit app (UI, cards, map)
├── src/
│   ├── transit.py             # station graph + shortest trips + directions
│   └── ranking.py             # filters, open-now logic, scoring, surprise pick
├── scripts/
│   ├── fetch_stations.py      # MBTA V3 API -> data/stations.csv
│   └── fetch_places.py        # Google Places API -> data/places.csv
├── data/
│   ├── stations.csv
│   └── places.csv
├── .streamlit/config.toml     # light theme
├── requirements.txt
└── .env.example
🛠️ Tech stack
Python, pandas
Streamlit for the web app
Folium + streamlit-folium for the map
MBTA V3 API for stations, routes and last-train schedules
Google Places API (New) for restaurants, ratings, prices and opening hours
⚠️ Assumptions & limitations
Travel times are estimates (2 min per stop, 5 min per transfer), not live arrival predictions. Green Line surface stops can take longer.
Walking time uses straight-line distance with a 1.3× detour factor, not real street routing.
Covers the subway only (Red, Orange, Blue, Green). It does not include buses, the Mattapan trolley or Commuter Rail.
Restaurant data is a snapshot from the Google Places API. Google returns at most 20 results per search, so dense areas may not list every restaurant (--deep helps).
Opening hours and prices come from Google and can be missing or out of date.
🔮 What's next
Live MBTA predictions instead of fixed per-stop estimates
Real walking directions
Bus routes
Saving favorites and sharing a pick with friends
👥 Team
