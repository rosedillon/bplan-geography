from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from bplan_geography import BplanNetworkLinks, BplanTimingGraph

from .conftest import FAST_TRACTION, SLOW_TRACTION

if TYPE_CHECKING:
    import pathlib


@pytest.fixture
def graph(cleaned: pathlib.Path) -> BplanTimingGraph:
    return BplanTimingGraph(cleaned)


class TestTimingGraph:
    def test_bus_and_tube_excluded(self, tmp_path: pathlib.Path) -> None:
        rows = [
            ("A", "B", "150", 30.0),
            ("A", "X", "BUS", 2.0),
            ("X", "B", "BUSXC", 2.0),
            ("A", "B", "LUL", 1.0),
        ]
        pd.DataFrame(
            [
                {
                    "from_tiploc": a,
                    "to_tiploc": b,
                    "traction_code": code,
                    "entry_speed": "-1",
                    "exit_speed": "-1",
                    "sectional_running_time_minutes": minutes,
                }
                for a, b, code, minutes in rows
            ]
        ).to_csv(tmp_path / "bplan_timing_links.csv", index=False)
        graph = BplanTimingGraph(tmp_path)
        # Neither the bus shortcut nor the Underground timing is open to
        # a train.
        assert graph.minimum_running_time("A", "B", "999") == pytest.approx(30.0)
        assert "X" not in graph

    def test_adjacent_pair_start_stop(self, graph: BplanTimingGraph) -> None:
        # A single-link journey starts from a stand and stops at one, so
        # it takes the combined variant (+03'15), not the passing time
        # (+02'00).
        minutes = graph.minimum_running_time("AAAA", "BBBB", FAST_TRACTION)
        assert minutes == pytest.approx(3.25)

    def test_fastest_variant(self, graph: BplanTimingGraph) -> None:
        # AAAA->BBBB also has a +09'00 record on a slow line; it must
        # not win.
        assert graph.graph["AAAA"]["BBBB"]["srt"][FAST_TRACTION] == pytest.approx(2.0)

    def test_multi_link_route(self, graph: BplanTimingGraph) -> None:
        # AAAA->BBBB start-from-stand (+02'30), BBBB->CCCC stop (+03'00,
        # no stop variant recorded so it falls back to passing).
        minutes = graph.minimum_running_time("AAAA", "CCCC", FAST_TRACTION)
        assert minutes == pytest.approx(2.5 + 3.0)

    def test_intermediate_point(self, graph: BplanTimingGraph) -> None:
        # AAAA and DDDD are not adjacent; the path runs via BBBB.
        assert graph.minimum_running_time("AAAA", "DDDD", FAST_TRACTION) is not None

    def test_exact_share_full(self, graph: BplanTimingGraph) -> None:
        _, share = graph.running_time_detail("AAAA", "CCCC", FAST_TRACTION)
        assert share == pytest.approx(1.0)

    def test_exact_share_partial(self, graph: BplanTimingGraph) -> None:
        # The slow traction is only timed on AAAA->BBBB; BBBB->CCCC
        # falls back to the fastest recorded traction, so the answer is
        # optimistic.
        _, share = graph.running_time_detail("AAAA", "CCCC", SLOW_TRACTION)
        assert share is not None
        assert 0.0 < share < 1.0

    def test_unknown_traction(self, graph: BplanTimingGraph) -> None:
        minutes, share = graph.running_time_detail("AAAA", "CCCC", "NOSUCH")
        assert minutes is not None
        assert share == pytest.approx(0.0)

    def test_unknown_tiploc_returns_none(self, graph: BplanTimingGraph) -> None:
        assert graph.minimum_running_time("ZZZZ", "AAAA", FAST_TRACTION) is None
        assert graph.minimum_running_time("AAAA", "ZZZZ", FAST_TRACTION) is None

    def test_unreachable_pair_returns_none(self, graph: BplanTimingGraph) -> None:
        # The graph is directed; nothing runs back from CCCC.
        assert graph.minimum_running_time("CCCC", "AAAA", FAST_TRACTION) is None

    def test_tiplocs_normalised(self, graph: BplanTimingGraph) -> None:
        assert graph.minimum_running_time(" aaaa ", "bbbb", FAST_TRACTION) == pytest.approx(
            graph.minimum_running_time("AAAA", "BBBB", FAST_TRACTION)
        )

    def test_membership_test(self, graph: BplanTimingGraph) -> None:
        assert "AAAA" in graph
        assert "aaaa" in graph
        assert "ZZZZ" not in graph

    def test_dropped_timing_link_leaves_no_edge(self, graph: BplanTimingGraph) -> None:
        assert not graph.graph.has_edge("CCCC", "DDDD")


class TestNetworkLinks:
    @pytest.fixture
    def links(self, cleaned: pathlib.Path) -> BplanNetworkLinks:
        return BplanNetworkLinks(cleaned)

    def test_single_running_line(self, links: BplanNetworkLinks) -> None:
        assert links.running_line_count("AAAA", "BBBB") == 1

    def test_running_line_count(self, links: BplanNetworkLinks) -> None:
        # BBBB->CCCC is recorded on both UM and DM.
        assert links.running_line_count("BBBB", "CCCC") == 2

    def test_unknown_pair_is_none(self, links: BplanNetworkLinks) -> None:
        assert links.running_line_count("AAAA", "ZZZZ") is None

    def test_distance_is_read(self, links: BplanNetworkLinks) -> None:
        assert links.distance_metres("AAAA", "BBBB") == pytest.approx(2000.0)

    def test_distance_of_unknown_pair_is_none(self, links: BplanNetworkLinks) -> None:
        assert links.distance_metres("AAAA", "ZZZZ") is None

    def test_case_insensitive(self, links: BplanNetworkLinks) -> None:
        assert links.running_line_count(" aaaa ", "bbbb") == 1

    def test_length_is_the_pair_count(self, links: BplanNetworkLinks) -> None:
        assert len(links) == 3  # A->B, B->C, B->D
