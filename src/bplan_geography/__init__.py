"""Parse Network Rail BPLAN Geography.

Clean an extract into CSVs once, then query them::

    from bplan_geography import BplanTimingGraph, clean_extract

    clean_extract(Path("PIF20260710570710068.txt"), Path("out"))
    # {'LOC': 12012, 'NWK': 42426, 'TLK': 1166850, 'TLD': 607}
    graph = BplanTimingGraph(Path("out"))
    graph.minimum_running_time("LEEDS", "YORK", "185")
    # 20.0
"""

from __future__ import annotations

from bplan_geography.network import BplanNetworkLinks
from bplan_geography.parsing import (
    COLUMNS,
    KEPT_RECORD_TYPES,
    OUTPUT_FILENAMES,
    ExtractHeader,
    clean_extract,
    iter_records,
    parse_srt_minutes,
    read_header,
)
from bplan_geography.timing import BplanTimingGraph

__all__ = [
    "COLUMNS",
    "KEPT_RECORD_TYPES",
    "OUTPUT_FILENAMES",
    "BplanNetworkLinks",
    "BplanTimingGraph",
    "ExtractHeader",
    "clean_extract",
    "iter_records",
    "parse_srt_minutes",
    "read_header",
]

__version__ = "0.1.0"
