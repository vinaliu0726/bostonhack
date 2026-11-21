"""Subway graph + shortest trips, built from data/stations.csv.

Nodes are parent stations (place-xxx), so transfer stations like Park Street
are already one node shared by Red and Green.

Search state is (station, route). Riding one stop costs 2 min; switching route
at a station costs 5 min (a transfer). Since every edge costs 2 or 5, this is a
small Dijkstra (BFS with weights) and returns, for every reachable station:
stops, transfers, ride minutes = stops * 2 + transfers * 5, and the legs.

Walking time is added in ranking.py (walk_min from places.csv).

Usage:
    g = TransitGraph.from_csv()
    trips = g.trips_from("place-harsq")       # {station_id: Trip}
    ride = g.ride_minutes("place-harsq")      # {station_id: minutes} -> ranking.rank_places
    print(g.describe(trips["place-kencl"]))
"""
import heapq
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
STATIONS_CSV = ROOT / "data" / "stations.csv"

MIN_PER_STOP = 2
MIN_PER_TRANSFER = 5

LINE_COLORS = {"Red": "#DA291C", "Orange": "#ED8B00", "Blue": "#003DA5", "Green": "#00843D"}


def base_route(route_id: str) -> str:
    """Internal ids split branches of one route ('Red:Ashmont'); strip that part."""
    return route_id.split(":")[0]


def route_name(route_id: str) -> str:
    """'Red' -> 'Red Line', 'Green-B' -> 'Green Line B'."""
    route_id = base_route(route_id)
    if route_id.startswith("Green-"):
        return f"Green Line {route_id.split('-')[1]}"
    return f"{route_id} Line"


def route_color(route_id: str) -> str:
    return LINE_COLORS.get(base_route(route_id).split("-")[0], "#555555")


@dataclass
class Leg:
    routes: list[str]              # every route that rides this whole leg, e.g. ["Green-B", "Green-C"]
    from_id: str
    to_id: str
    stops: int
    toward: str                    # terminal in the direction of travel
    path: list[str] = field(default_factory=list)   # station ids, from -> to


@dataclass
class Trip:
    origin_id: str
    dest_id: str
    stops: int
    transfers: int
    legs: list[Leg]

    @property
    def minutes(self) -> int:
        return self.stops * MIN_PER_STOP + self.transfers * MIN_PER_TRANSFER

    @property
    def path(self) -> list[str]:
        """All station ids along the trip (for drawing on the map)."""
        if not self.legs:
            return [self.origin_id]
        out = [self.legs[0].from_id]
        for leg in self.legs:
            out += leg.path[1:]
        return out


class TransitGraph:
    def __init__(self, stations: pd.DataFrame):
        self.df = stations
        info = stations.drop_duplicates("station_id").set_index("station_id")
        self.name = info["station_name"].to_dict()
        self.coords = {s: (r.lat, r.lon) for s, r in info.iterrows()}

        # adj[station] -> set of (neighbor, route_id); edges are two-way.
        self.adj: dict[str, set[tuple[str, str]]] = {s: set() for s in self.name}
        # Station order per pattern, to know which terminal a leg is heading to.
        self.patterns: list[tuple[str, list[str]]] = []
        n_patterns = stations.groupby("route_id")["pattern_id"].nunique()
        for (route_id, _), grp in stations.sort_values("seq").groupby(["route_id", "pattern_id"]):
            seq = grp["station_id"].tolist()
            if n_patterns[route_id] > 1:
                # Red has two branches (Ashmont / Braintree): give each its own id so
                # switching branches at JFK/UMass counts as a transfer.
                route_id = f"{route_id}:{self.name[seq[-1]]}"
            self.patterns.append((route_id, seq))
            for a, b in zip(seq, seq[1:]):
                self.adj[a].add((b, route_id))
                self.adj[b].add((a, route_id))
        self.edge_routes: dict[frozenset, set[str]] = {}
        for a, nbrs in self.adj.items():
            for b, r in nbrs:
                self.edge_routes.setdefault(frozenset((a, b)), set()).add(r)

    @classmethod
    def from_csv(cls, path: Path = STATIONS_CSV) -> "TransitGraph":
        return cls(pd.read_csv(path))

    # ------------------------------------------------------------ stations
    def station_table(self) -> pd.DataFrame:
        """One row per station: station_id, station_name, lines, lat, lon (for the sidebar/map)."""
        lines = (self.df.assign(line=self.df["route_id"].map(route_name))
                 .groupby("station_id")["line"].apply(lambda s: ", ".join(sorted(set(s)))))
        out = self.df.drop_duplicates("station_id")[["station_id", "station_name", "lat", "lon"]]
        return out.assign(lines=out["station_id"].map(lines)).sort_values("station_name")

    def station_id(self, name: str) -> str:
        """Look up an id by exact station name."""
        for sid, n in self.name.items():
            if n == name:
                return sid
        raise KeyError(f"No station named {name!r}")

    # ------------------------------------------------------------ search
    def trips_from(self, origin_id: str) -> dict[str, Trip]:
        """Best trip from origin to every reachable station."""
        if origin_id not in self.adj:
            raise KeyError(f"Unknown station id {origin_id!r}")
        start_routes = {r for _, r in self.adj[origin_id]}
        # heap entries: (minutes, transfers, stops, station, route)
        heap = [(0, 0, 0, origin_id, r) for r in start_routes]
        best = {(origin_id, r): (0, 0, 0) for r in start_routes}
        prev: dict[tuple, tuple | None] = {(origin_id, r): None for r in start_routes}
        heapq.heapify(heap)
        while heap:
            cost, xfers, stops, s, r = heapq.heappop(heap)
            if best.get((s, r)) != (cost, xfers, stops):
                continue
            moves = [(n, r, cost + MIN_PER_STOP, xfers, stops + 1)
                     for n, nr in self.adj[s] if nr == r]                  # ride on
            moves += [(s, nr, cost + MIN_PER_TRANSFER, xfers + 1, stops)
                      for nr in {x for _, x in self.adj[s]} if nr != r]  # transfer here
            for n, nr, c, x, st in moves:
                key = (n, nr)
                if key not in best or (c, x, st) < best[key]:
                    best[key] = (c, x, st)
                    prev[key] = (s, r)
                    heapq.heappush(heap, (c, x, st, n, nr))

        # Best state per station, then rebuild the legs.
        best_state: dict[str, tuple] = {}
        for (s, r), v in best.items():
            if s not in best_state or v < best[best_state[s]]:
                best_state[s] = (s, r)
        trips = {}
        for s, state in best_state.items():
            _, xfers, stops = best[state]
            chain = []
            while state is not None:
                chain.append(state)
                state = prev[state]
            chain.reverse()
            trips[s] = Trip(origin_id, s, stops, xfers, self._legs(chain))
        return trips

    def trip(self, origin_id: str, dest_id: str) -> Trip | None:
        return self.trips_from(origin_id).get(dest_id)

    def ride_minutes(self, origin_id: str) -> dict[str, int]:
        """{station_id: ride minutes} — pass to ranking.rank_places(ride_min=...)."""
        return {s: t.minutes for s, t in self.trips_from(origin_id).items()}

    # ------------------------------------------------------------ legs / text
    def _legs(self, chain: list[tuple[str, str]]) -> list[Leg]:
        """Group a (station, route) chain into legs; drop transfer-only steps."""
        legs, cur = [], None
        for (s0, r0), (s1, r1) in zip(chain, chain[1:]):
            if s0 == s1:                 # transfer step
                cur = None
                continue
            if cur is None:
                cur = [r0, [s0]]
                legs.append(cur)
            cur[1].append(s1)
        out = []
        for route, path in legs:
            # Any route that covers every edge of this leg works (e.g. Green B/C/D on the trunk).
            ok = set.intersection(*(self.edge_routes[frozenset(e)] for e in zip(path, path[1:])))
            ok.add(route)
            out.append(Leg(sorted(ok), path[0], path[-1], len(path) - 1,
                           self._toward(ok, path[0], path[-1]), path))
        return out

    def _toward(self, routes: set[str], a: str, b: str) -> str:
        ends = []
        for r, seq in self.patterns:
            if r in routes and a in seq and b in seq:
                end = seq[-1] if seq.index(b) > seq.index(a) else seq[0]
                if self.name[end] not in ends:
                    ends.append(self.name[end])
        return " / ".join(ends)

    def leg_label(self, leg: Leg) -> str:
        """'Red Line' or 'Green Line B/C/D'."""
        if all(r.startswith("Green-") for r in leg.routes) and len(leg.routes) > 1:
            return "Green Line " + "/".join(r.split("-")[1] for r in leg.routes)
        return route_name(leg.routes[0])

    def leg_color(self, leg: Leg) -> str:
        return route_color(leg.routes[0])

    def describe(self, trip: Trip) -> list[str]:
        """Human-readable steps, one string per leg."""
        if not trip.legs:
            return [f"You're already at {self.name[trip.dest_id]}"]
        steps = []
        for i, leg in enumerate(trip.legs):
            verb = "Take" if i == 0 else "Transfer to"
            s = "stop" if leg.stops == 1 else "stops"
            steps.append(f"{verb} the {self.leg_label(leg)} toward {leg.toward}, "
                         f"{leg.stops} {s} to {self.name[leg.to_id]}")
        return steps

    def summary(self, trip: Trip) -> str:
        """'4 stops · 1 transfer · ~13 min ride'."""
        x = "transfer" if trip.transfers == 1 else "transfers"
        s = "stop" if trip.stops == 1 else "stops"
        return f"{trip.stops} {s} · {trip.transfers} {x} · ~{trip.minutes} min ride"


if __name__ == "__main__":
    # Quick check: python -m src.transit [origin name] [destination name]
    import sys
    g = TransitGraph.from_csv()
    origin = sys.argv[1] if len(sys.argv) > 1 else "Harvard"
    dests = sys.argv[2:] or ["Kenmore", "Chinatown", "Airport", "Coolidge Corner", "Harvard"]
    trips = g.trips_from(g.station_id(origin))
    print(f"{len(g.name)} stations, {len(trips)} reachable from {origin}\n")
    for d in dests:
        t = trips[g.station_id(d)]
        print(f"{origin} -> {d}: {g.summary(t)}")
        for step in g.describe(t):
            print("   ", step)
