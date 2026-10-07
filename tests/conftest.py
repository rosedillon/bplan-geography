"""Synthetic BPLAN extracts for the tests.

A real extract is about 90 MB and licensed through the Rail Data
Marketplace, so these build small ones with the same field geometry:
the same tab-separated column positions, ``+MM'SS`` running times,
entry and exit speed convention and PIF header. The field indices are
taken from real records, such as

    LOC     A       AACHEN  Aachen  01-01-1995 00:00:00
    848093  121300  O       3       00005   N TLK   A       ABARASQ
    ABRYSTH BUS     BUSATW          60              0       0
    21-05-2023 00:00:00             +37'00

so a change to the index constants in `bplan_geography.parsing` shows up
here.

The toy network is a straight line with a branch::

    AAAA --2min-- BBBB --3min-- CCCC
                    \\--4min-- DDDD

with a slower traction and a multi-track segment to exercise the
fallbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib

HEADER = (
    "PIF\t1\tCENTRE\tNR\t17-05-2026 00:00:00\t12-12-2026 23:59:59\tI\tD\t10-07-2026 19:00:00\t1"
)

# Traction codes used in the fixtures. "185" is timed on every link;
# "150" only on some, so the fastest-traction fallback gets exercised.
FAST_TRACTION = "185"
SLOW_TRACTION = "150"


def loc(
    tiploc: str,
    name: str,
    easting: str = "450000",
    northing: str = "430000",
    stanox: str = "12345",
) -> str:
    """A LOC record.

    Fields read: 2 tiploc, 3 name, 6 easting, 7 northing, 10 stanox.
    """
    fields = [
        "LOC",
        "A",
        tiploc,
        name,
        "01-01-1995 00:00:00",
        "",
        easting,
        northing,
        "O",
        "3",
        stanox,
        "N",
        " ",
    ]
    return "\t".join(fields)


def nwk(
    from_tiploc: str,
    to_tiploc: str,
    running_line: str = "ML",
    distance_metres: str = "01000",
    route_availability: str = "4",
) -> str:
    """An NWK record.

    Fields read: 2 from, 3 to, 4 line, 6/7 dates, 8 direction,
    10 distance, 14 route availability.
    """
    fields = [
        "NWK",
        "A",
        from_tiploc,
        to_tiploc,
        running_line,
        "",
        "11-12-2022 00:00:00",
        "",
        "D",
        "D",
        distance_metres,
        "N",
        "N",
        "N",
        route_availability,
        "N",
        " ",
        "0",
        "",
    ]
    return "\t".join(fields)


def tlk(
    from_tiploc: str,
    to_tiploc: str,
    traction: str,
    srt: str,
    running_line: str = "ML",
    entry_speed: str = "-1",
    exit_speed: str = "-1",
) -> str:
    """A TLK record.

    Fields read: 2 from, 3 to, 4 line, 5 traction, 7 speed, 9 entry,
    10 exit, 11/12 dates, 13 running time.
    """
    fields = [
        "TLK",
        "A",
        from_tiploc,
        to_tiploc,
        running_line,
        traction,
        "     ",
        "60",
        " ",
        entry_speed,
        exit_speed,
        "21-05-2023 00:00:00",
        "",
        srt,
        "",
    ]
    return "\t".join(fields)


def tld(traction: str, max_speed: str, description: str, category: str = "D") -> str:
    """A TLD record.

    Fields read: 2 traction, 4 max speed, 6 description, 7 category.
    """
    fields = ["TLD", "A", traction, "     ", max_speed, " ", description, category, " ", max_speed]
    return "\t".join(fields)


def extract_lines() -> list[str]:
    """The whole synthetic extract, with records to be skipped."""
    lines = [
        HEADER,
        # Record types the parser must skip entirely.
        "REF\tA\tACC\t \tUndefined",
        "PLT\tA\tAAAA\t1\t\t\t\t\t\t\t",
        # Locations.
        loc("AAAA", "Aytown", easting="529500", northing="182700", stanox="00001"),
        loc("BBBB", "Beeford", easting="530200", northing="183200", stanox="00002"),
        loc("CCCC", "Ceeville", stanox="00003"),
        loc("DDDD", "Deetown", stanox="00004"),
        # A short LOC that must be skipped rather than crash the parse.
        "LOC\tA\tSHORT\tToo few fields",
        # Topology. B->C is recorded on two running lines (multi-track).
        nwk("AAAA", "BBBB", distance_metres="02000"),
        nwk("BBBB", "CCCC", running_line="UM", distance_metres="03000"),
        nwk("BBBB", "CCCC", running_line="DM", distance_metres="03000"),
        nwk("BBBB", "DDDD", distance_metres="04000"),
        # Timings, passing at both ends.
        tlk("AAAA", "BBBB", FAST_TRACTION, "+02'00"),
        tlk("BBBB", "CCCC", FAST_TRACTION, "+03'00"),
        tlk("BBBB", "DDDD", FAST_TRACTION, "+04'00"),
        # The slow traction is only timed on the first link; elsewhere
        # the fastest-traction fallback has to cover it.
        tlk("AAAA", "BBBB", SLOW_TRACTION, "+02'30"),
        # A second, slower variant of AAAA->BBBB: the faster one must
        # win.
        tlk("AAAA", "BBBB", FAST_TRACTION, "+09'00", running_line="SL"),
        # Start-from-stand and stop-to-stand variants of the first link.
        tlk("AAAA", "BBBB", FAST_TRACTION, "+02'30", entry_speed="0", exit_speed="-1"),
        tlk("AAAA", "BBBB", FAST_TRACTION, "+02'45", entry_speed="-1", exit_speed="0"),
        tlk("AAAA", "BBBB", FAST_TRACTION, "+03'15", entry_speed="0", exit_speed="0"),
        # A timing link with an unparseable running time: dropped.
        tlk("CCCC", "DDDD", FAST_TRACTION, ""),
        # Traction definitions.
        tld(FAST_TRACTION, "100", "Class 185 Desiro"),
        tld(SLOW_TRACTION, "75", "Class 150 Sprinter"),
    ]
    return lines


@pytest.fixture
def extract(tmp_path: pathlib.Path) -> pathlib.Path:
    """A synthetic BPLAN extract on disk."""
    path = tmp_path / "PIF_TEST.txt"
    path.write_text("\n".join(extract_lines()) + "\n", encoding="latin-1")
    return path


@pytest.fixture
def cleaned(extract: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    """A directory of cleaned CSVs from the synthetic extract."""
    from bplan_geography import clean_extract

    output = tmp_path / "cleaned"
    clean_extract(extract, output)
    return output
