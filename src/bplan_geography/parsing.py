"""Stream a BPLAN Geography extract and write one CSV per record type.

BPLAN is Network Rail's master geography, the physical network as the
train planning system sees it. The extract is a tab-delimited text file
with one record per line and the record type in the first column. A
full extract is around 90 MB and 1.2 million lines, so it is streamed
rather than loaded.

Four record types are kept:

``LOC``
    The TIPLOC register: code, name, OSGB easting/northing, STANOX.
``NWK``
    Network links: the physical topology between adjacent TIPLOCs, with
    a running line, direction, distance in metres and route
    availability.
``TLK``
    Timing links: the minimum sectional running time between two
    adjacent TIPLOCs for one traction and timing load on one running
    line, in ``+MM'SS`` form.
``TLD``
    The traction and timing load definitions that ``TLK``'s traction
    code refers to: maximum speed, description, category.

``PLT`` (platforms), ``REF`` (reference codes) and the other types make
up most of the file, and a prefix test skips them before any field
splitting.

On the field layout
-------------------
The column positions below were worked out from real extracts, not
taken from an interface specification, and then cross-checked. The
``LOC`` eastings and northings for Euston (529500, 182700) and Kings
Cross (530200, 183200) match published OSGB grid references, and
``NWK`` and ``TLK`` values around Leeds and on the slow Aberdare branch
give believable distances and speeds. Even so, no specification has
confirmed the layout.

The Open Rail Data wiki describes the format:
https://wiki.openraildata.com/index.php/BPLAN_Geography
"""

from __future__ import annotations

import csv
import datetime
import logging
import re

# Callable is needed at runtime: the RowBuilder alias below is
# evaluated.
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Record types this module extracts, in output order.
KEPT_RECORD_TYPES = ("LOC", "NWK", "TLK", "TLD")

LOC_COLUMNS = ["tiploc", "name", "easting", "northing", "stanox"]
NWK_COLUMNS = [
    "from_tiploc",
    "to_tiploc",
    "running_line",
    "start_date",
    "end_date",
    "direction",
    "distance_metres",
    "route_availability",
]
TLK_COLUMNS = [
    "from_tiploc",
    "to_tiploc",
    "running_line",
    "traction_code",
    "timing_load_speed_mph",
    "entry_speed",
    "exit_speed",
    "start_date",
    "end_date",
    "sectional_running_time_minutes",
]
TLD_COLUMNS = ["traction_code", "max_speed_mph", "description", "category"]

COLUMNS: dict[str, list[str]] = {
    "LOC": LOC_COLUMNS,
    "NWK": NWK_COLUMNS,
    "TLK": TLK_COLUMNS,
    "TLD": TLD_COLUMNS,
}

OUTPUT_FILENAMES = {
    "LOC": "bplan_locations.csv",
    "NWK": "bplan_network_links.csv",
    "TLK": "bplan_timing_links.csv",
    "TLD": "bplan_traction_loads.csv",
}

# Fields each record type needs for the columns read below (the
# highest index used, plus one). A shorter line is skipped.
MINIMUM_FIELDS = {"LOC": 11, "NWK": 15, "TLK": 14, "TLD": 8}

# A sectional running time, e.g. ``+04'00`` -> sign, minutes, seconds.
SRT_PATTERN = re.compile(r"^([+-]?)(\d+)'(\d+)$")

# One parsed output row. Values are the raw strings from the extract,
# except the sectional running time, which is converted to minutes.
Row = dict[str, "str | float | None"]


def parse_srt_minutes(value: str) -> float | None:
    """Minutes from a BPLAN ``+MM'SS`` running-time field, or ``None``.

    >>> parse_srt_minutes("+04'00")
    4.0
    >>> parse_srt_minutes("+00'30")
    0.5
    >>> parse_srt_minutes("") is None
    True
    """
    match = SRT_PATTERN.match(value.strip())
    if not match:
        return None
    sign, minutes, seconds = match.groups()
    total = int(minutes) + int(seconds) / 60
    return -total if sign == "-" else total


@dataclass(frozen=True, slots=True)
class ExtractHeader:
    """The ``PIF`` header line that opens an extract.

    An extract is a snapshot with a validity window, and nothing
    complains when analysis runs against the wrong one, so it is worth
    logging which one was read.
    """

    owner: str
    valid_from: datetime.datetime | None
    valid_to: datetime.datetime | None
    generated: datetime.datetime | None

    @property
    def description(self) -> str:
        def fmt(value: datetime.datetime | None) -> str:
            return value.date().isoformat() if value else "?"

        return f"{self.owner} extract, valid {fmt(self.valid_from)} to {fmt(self.valid_to)}"


_HEADER_TIMESTAMP = "%d-%m-%Y %H:%M:%S"


def _timestamp(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(value.strip(), _HEADER_TIMESTAMP)
    except ValueError:
        return None


def read_header(path: pathlib.Path) -> ExtractHeader | None:
    """Read the ``PIF`` header from the first line of an extract.

    Returns ``None`` if the file does not start with one, which is the
    case for a hand-trimmed extract.
    """
    with path.open(encoding="latin-1") as handle:
        first = handle.readline()
    if not first.startswith("PIF\t"):
        return None
    fields = first.rstrip("\n").split("\t")
    if len(fields) < 9:
        return None
    return ExtractHeader(
        owner=fields[3].strip(),
        valid_from=_timestamp(fields[4]),
        valid_to=_timestamp(fields[5]),
        generated=_timestamp(fields[8]),
    )


def iter_records(path: pathlib.Path) -> Iterator[tuple[str, list[str]]]:
    """Stream ``(record_type, fields)`` for the kept record types only.

    The file is read as latin-1, not UTF-8. International TIPLOC names
    (Eurostar destinations among them) come in a mix of encodings, and
    latin-1 decodes any byte, so one odd name cannot stop the read.
    """
    prefixes = tuple(f"{record_type}\t" for record_type in KEPT_RECORD_TYPES)
    with path.open(encoding="latin-1") as handle:
        for line in handle:
            # Most lines are record types that are skipped, and
            # splitting into fields is the slow part, so test the prefix
            # first.
            if not line.startswith(prefixes):
                continue
            fields = line.rstrip("\n").split("\t")
            yield fields[0], fields


def _location(fields: list[str]) -> Row | None:
    return {
        "tiploc": fields[2].strip().upper(),
        "name": fields[3].strip(),
        "easting": fields[6] or None,
        "northing": fields[7] or None,
        "stanox": fields[10].strip(),
    }


def _network_link(fields: list[str]) -> Row | None:
    return {
        "from_tiploc": fields[2].strip().upper(),
        "to_tiploc": fields[3].strip().upper(),
        "running_line": fields[4].strip(),
        "start_date": fields[6],
        "end_date": fields[7],
        "direction": fields[8].strip(),
        "distance_metres": fields[10] or None,
        "route_availability": fields[14].strip(),
    }


def _timing_link(fields: list[str]) -> Row | None:
    running_time = parse_srt_minutes(fields[13])
    if running_time is None:
        # The running time is the point of a timing link, so a record
        # without a readable one is dropped.
        return None
    return {
        "from_tiploc": fields[2].strip().upper(),
        "to_tiploc": fields[3].strip().upper(),
        "running_line": fields[4].strip(),
        "traction_code": fields[5].strip(),
        "timing_load_speed_mph": fields[7] or None,
        # 0 means starting or stopping at this end, -1 passing at speed.
        "entry_speed": fields[9].strip(),
        "exit_speed": fields[10].strip(),
        "start_date": fields[11],
        "end_date": fields[12],
        "sectional_running_time_minutes": running_time,
    }


def _traction_load(fields: list[str]) -> Row | None:
    return {
        "traction_code": fields[2].strip(),
        "max_speed_mph": fields[4] or None,
        "description": fields[6].strip(),
        "category": fields[7].strip(),
    }


RowBuilder = Callable[[list[str]], "Row | None"]

ROW_BUILDERS: dict[str, RowBuilder] = {
    "LOC": _location,
    "NWK": _network_link,
    "TLK": _timing_link,
    "TLD": _traction_load,
}

_PROGRESS_EVERY = 500_000


def clean_extract(source: pathlib.Path, output_dir: pathlib.Path) -> dict[str, int]:
    """Stream *source* and write one CSV per record type.

    Returns the number of rows written for each record type, such as
    ``{"LOC": 12012, "NWK": 42426, "TLK": 1166850, "TLD": 607}``.

    The files written are named by :data:`OUTPUT_FILENAMES` and are what
    :class:`~bplan_geography.timing.BplanTimingGraph` and
    :class:`~bplan_geography.network.BplanNetworkLinks` read back.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    header = read_header(source)
    if header:
        logger.info("BPLAN %s", header.description)

    counts = dict.fromkeys(KEPT_RECORD_TYPES, 0)
    skipped_short = dict.fromkeys(KEPT_RECORD_TYPES, 0)
    handles = []
    try:
        writers: dict[str, csv.DictWriter[str]] = {}
        for record_type in KEPT_RECORD_TYPES:
            handle = (output_dir / OUTPUT_FILENAMES[record_type]).open("w", newline="")
            handles.append(handle)
            writer = csv.DictWriter(handle, fieldnames=COLUMNS[record_type])
            writer.writeheader()
            writers[record_type] = writer

        logger.info("Streaming BPLAN Geography from %s", source)
        for line_number, (record_type, fields) in enumerate(iter_records(source), start=1):
            if len(fields) < MINIMUM_FIELDS[record_type]:
                skipped_short[record_type] += 1
                continue
            row = ROW_BUILDERS[record_type](fields)
            if row is None:
                continue
            writers[record_type].writerow(row)
            counts[record_type] += 1
            if line_number % _PROGRESS_EVERY == 0:
                logger.info("Processed %d kept lines", line_number)
    finally:
        for handle in handles:
            handle.close()

    for record_type, skipped in skipped_short.items():
        if skipped:
            logger.warning(
                "%d %s record(s) had fewer than %d fields and were skipped",
                skipped,
                record_type,
                MINIMUM_FIELDS[record_type],
            )
    logger.info(
        "Cleaned BPLAN Geography: %s",
        ", ".join(f"{rt}={n:,}" for rt, n in counts.items()),
    )
    return counts
