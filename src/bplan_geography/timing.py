"""Minimum sectional running times as a routable graph.

``TLK`` records give the minimum running time between *adjacent* timing
points. Two stations a train calls at are usually not adjacent, because
the train passes intermediate timing points between them, so working out
how fast a train could get from A to B means summing along a path.
"""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING, Any, cast

import networkx as nx
import pandas as pd

from bplan_geography.parsing import OUTPUT_FILENAMES

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# BPLAN records entry/exit speed 0 when the train starts from or stops
# at that end of the link, and -1 when it passes at line speed.
_STARTS_OR_STOPS = "0"

# Traction codes for ships, the Underground and the Tyne and Wear
# Metro. Their timings are not trains on Network Rail track, and
# neither is any code starting ``BUS``. A bus timed from Brighton to
# North Wembley would otherwise put a Brighton to Victoria train at 35
# minutes.
NON_RAIL_TRACTION = frozenset({"SHIP", "HSS", "SEALYX", "LUL", "20", "TWM"})

# Timing kind by ``starts + 2 * stops``.
_KIND_BY_CODE = {0: "srt", 1: "srt_start", 2: "srt_stop", 3: "srt_start_stop"}


class BplanTimingGraph:
    """Minimum running time between any two TIPLOCs, by traction.

    Build it once from a cleaned ``bplan_timing_links.csv``; each lookup
    is then one shortest-path search.

    Where several timing links exist for the same (from, to, traction),
    such as different running lines or superseded variants, the fastest
    is kept. The graph answers what is *achievable*: if any recorded
    variant is faster, a proposed timing at or above it cannot be shown
    to be infeasible from this data alone.
    """

    def __init__(self, cleaned_dir: pathlib.Path) -> None:
        """Load timing links from a directory written by ``clean``.

        Parameters
        ----------
        cleaned_dir
            A directory containing ``bplan_timing_links.csv``.
        """
        path = cleaned_dir / OUTPUT_FILENAMES["TLK"]
        logger.info("Loading BPLAN timing links from %s", path)
        links = pd.read_csv(path, dtype=str)
        links["sectional_running_time_minutes"] = pd.to_numeric(
            links["sectional_running_time_minutes"], errors="coerce"
        )
        links = links.dropna(subset=["sectional_running_time_minutes"])
        code = links["traction_code"].fillna("").str.strip().str.upper()
        links = links[~(code.str.startswith("BUS") | code.isin(NON_RAIL_TRACTION))]

        # Older cleaned outputs predate the entry/exit speed columns;
        # treat those as passing timings throughout.
        if "entry_speed" not in links.columns:
            links["entry_speed"] = "-1"
            links["exit_speed"] = "-1"
        links["starts"] = links["entry_speed"].astype(str).str.strip().eq(_STARTS_OR_STOPS)
        links["stops"] = links["exit_speed"].astype(str).str.strip().eq(_STARTS_OR_STOPS)

        links["kind"] = (links["starts"].astype(int) + 2 * links["stops"].astype(int)).map(
            _KIND_BY_CODE
        )

        # Fastest time per link, kind and traction in one group-by;
        # grouping link by link took about 25 seconds on a national
        # extract.
        minutes = "sectional_running_time_minutes"
        link = ["from_tiploc", "to_tiploc"]
        fastest = links.groupby([*link, "kind", "traction_code"])[minutes].min()
        edges: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
        # pandas types a multi-column group key as Hashable.
        for key, value in fastest.items():
            origin, destination, kind, traction = cast("tuple[str, str, str, str]", key)
            empty: dict[str, dict[str, float]] = {k: {} for k in _KIND_BY_CODE.values()}
            edges.setdefault((origin, destination), empty)[kind][traction] = float(value)

        # A link with no passing timing takes the fastest of any kind.
        no_passing = {pair for pair, timings in edges.items() if not timings["srt"]}
        if no_passing:
            any_kind = links.groupby([*link, "traction_code"])[minutes].min()
            for key, value in any_kind.items():
                origin, destination, traction = cast("tuple[str, str, str]", key)
                if (origin, destination) in no_passing:
                    edges[(origin, destination)]["srt"][traction] = float(value)

        self.graph: nx.DiGraph[str] = nx.DiGraph()
        for (origin, destination), timings in sorted(edges.items()):
            self.graph.add_edge(origin, destination, **timings)

        logger.info(
            "Built timing graph: %d TIPLOCs, %d directed links",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

    def __contains__(self, tiploc: str) -> bool:
        return tiploc.strip().upper() in self.graph

    @staticmethod
    def _weight_for(traction_code: str) -> Callable[[str, str, dict[str, Any]], float | None]:
        """Weight links by this traction's time, else the fastest."""

        def weight(_from: str, _to: str, data: dict[str, Any]) -> float | None:
            timings = data.get("srt", {})
            if traction_code in timings:
                result: float = timings[traction_code]
                return result
            return min(timings.values()) if timings else None

        return weight

    @staticmethod
    def _timing(data: dict[str, Any], kind: str, traction_code: str) -> tuple[float | None, bool]:
        """A link's timing of *kind*, and whether the traction matched.

        Falls back to the passing timing where the link has no
        start/stop variant, and to the fastest recorded traction where
        the requested code has no entry at all.
        """
        for key in (kind, "srt"):
            timings = data.get(key) or {}
            if traction_code in timings:
                return timings[traction_code], True
        timings = data.get(kind) or data.get("srt") or {}
        return (min(timings.values()), False) if timings else (None, False)

    def minimum_running_time(
        self, from_tiploc: str, to_tiploc: str, traction_code: str
    ) -> float | None:
        """Minimum running time in minutes; ``None`` if unroutable."""
        return self.running_time_detail(from_tiploc, to_tiploc, traction_code)[0]

    def running_time_detail(
        self, from_tiploc: str, to_tiploc: str, traction_code: str
    ) -> tuple[float | None, float | None]:
        """Minimum running time, and the share timed for this traction.

        The route taken is the fastest passing path. Its first link then
        takes the start-from-stand timing and its last link the stop
        timing, because a calling train has to accelerate away and brake
        to a stand, and BPLAN times those separately. A single-link
        journey takes the combined start-and-stop timing.

        Returns ``(minutes, exact_share)``, where ``exact_share`` is the
        fraction of the total contributed by links that had a timing for
        *traction_code* itself rather than the fastest-traction
        fallback. A low share means the answer is optimistic for this
        traction.
        """
        origin = from_tiploc.strip().upper()
        destination = to_tiploc.strip().upper()
        if origin not in self.graph or destination not in self.graph:
            return None, None
        try:
            path = nx.dijkstra_path(
                self.graph, origin, destination, weight=self._weight_for(traction_code)
            )
        except nx.NetworkXNoPath:
            return None, None

        edges = list(itertools.pairwise(path))
        if not edges:
            return 0.0, None

        total = 0.0
        exact = 0.0
        last_index = len(edges) - 1
        for index, (start, end) in enumerate(edges):
            kind = _timing_kind(is_first=index == 0, is_last=index == last_index)
            minutes, matched = self._timing(self.graph[start][end], kind, traction_code)
            if minutes is None:
                return None, None
            total += minutes
            if matched:
                exact += minutes
        return total, (exact / total if total else None)


def _timing_kind(*, is_first: bool, is_last: bool) -> str:
    if is_first and is_last:
        return "srt_start_stop"
    if is_first:
        return "srt_start"
    if is_last:
        return "srt_stop"
    return "srt"
