"""Physical topology from the ``NWK`` records."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import pandas as pd

from bplan_geography.parsing import OUTPUT_FILENAMES

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)


class BplanNetworkLinks:
    """Distinct running lines recorded between each pair of TIPLOCs.

    More than one distinct ``running_line`` between the same pair is as
    close as BPLAN Geography gets to saying a segment is multi-track.

    It is not a count of tracks or of platforms. Platforms are in
    BPLAN's ``PLT`` records, which are not parsed here, and the running
    line labels have not been checked against a specification. The count
    is useful context for a person looking at a possible headway
    conflict, but should not be used to dismiss one automatically.
    """

    def __init__(self, cleaned_dir: pathlib.Path) -> None:
        path = cleaned_dir / OUTPUT_FILENAMES["NWK"]
        logger.info("Loading BPLAN network links from %s", path)
        links = pd.read_csv(path, dtype=str)
        links = links.dropna(subset=["from_tiploc", "to_tiploc", "running_line"])
        counts = links.groupby(["from_tiploc", "to_tiploc"])["running_line"].nunique()
        self._counts: dict[tuple[str, str], int] = {
            _pair(key): int(count) for key, count in counts.items()
        }

        distances = links.dropna(subset=["distance_metres"]).copy()
        distances["distance_metres"] = pd.to_numeric(distances["distance_metres"], errors="coerce")
        distances = distances.dropna(subset=["distance_metres"])
        shortest = distances.groupby(["from_tiploc", "to_tiploc"])["distance_metres"].min()
        self._distances: dict[tuple[str, str], float] = {
            _pair(key): float(metres) for key, metres in shortest.items()
        }

    def running_line_count(self, from_tiploc: str, to_tiploc: str) -> int | None:
        """Distinct running lines on this directed segment, if known."""
        return self._counts.get(_key(from_tiploc, to_tiploc))

    def distance_metres(self, from_tiploc: str, to_tiploc: str) -> float | None:
        """Shortest recorded link distance in metres, if known.

        This is one link between adjacent timing points, not a route.
        """
        return self._distances.get(_key(from_tiploc, to_tiploc))

    def __len__(self) -> int:
        return len(self._counts)


def _key(from_tiploc: str, to_tiploc: str) -> tuple[str, str]:
    return from_tiploc.strip().upper(), to_tiploc.strip().upper()


def _pair(key: object) -> tuple[str, str]:
    """Normalise a two-level pandas groupby key into a TIPLOC pair."""
    origin, destination = cast("tuple[str, str]", key)
    return _key(origin, destination)
