# bplan-geography

Parse Network Rail's BPLAN Geography extract, the physical rail network
as the train planning system sees it, and ask how quickly a train could
get between two points.

Network Rail uses BPLAN to check that a timetable is physically
possible. The extract is a 90 MB tab-delimited text file with a dozen
record types mixed together, no header row, no schema, and running
times written as `+04'00`. This package turns it into CSVs and a
routable graph of minimum running times.

```python
from pathlib import Path
from bplan_geography import clean_extract, BplanTimingGraph

clean_extract(Path("PIF20260710570710068.txt"), Path("bplan"))
# {'LOC': 12012, 'NWK': 42426, 'TLK': 1166850, 'TLD': 607}

graph = BplanTimingGraph(Path("bplan"))
graph.minimum_running_time("LEEDS", "YORK", "185")
# 20.0 (minutes for a Class 185, stop to stop)
```

## Install

Python 3.11 or later.

```sh
pip install git+https://github.com/rosedillon/bplan-geography
```

or, from a clone, `pip install .`. It depends on pandas and networkx.

## Getting BPLAN

BPLAN Geography is on the [Rail Data Marketplace](https://raildata.org.uk),
which holds extracts back to 2022. Registration is free and the dataset
is called "BPLAN Geography". The file you download has a name like
`PIF20260710570710068.txt`.

The [Open Rail Data wiki](https://wiki.openraildata.com/index.php/BPLAN_Geography)
describes the format.

## Clean once, then query

Cleaning a full extract takes a few seconds:

```console
$ bplan-geography clean PIF20260710570710068.txt -o bplan
NR extract, valid 2026-05-17 to 2026-12-12
LOC     12,012  -> bplan_locations.csv
NWK     42,426  -> bplan_network_links.csv
TLK  1,166,850  -> bplan_timing_links.csv
TLD        607  -> bplan_traction_loads.csv
```

The first line is the extract's validity window, read from its header.
Check it matches the period you are studying.

Then ask how fast a train could get between two places, by TIPLOC:

```console
$ bplan-geography time LEEDS YORK -d bplan -t 185
LEEDS -> YORK (traction 185): 20.0 min

$ bplan-geography time MNCRPIC LEEDS -d bplan -t 185
MNCRPIC -> LEEDS (traction 185): 44.0 min
```

These are minimum times: what the network allows, with no pathing,
performance or dwell allowances. They come out a little under real
timetabled journeys. Leeds to York is timetabled at around 23 to 25
minutes against the 20 above.

Or ask about the physical link between two adjacent points:

```console
$ bplan-geography lines LEEDS YORK -d bplan
LEEDS -> YORK
  distinct running lines  1
  link distance           37,013 m
```

Add `--json` to any subcommand for machine-readable output, and `-v` to
log progress.

## When the traction code is not timed

BPLAN times each link for each traction and timing load code. A link
often has no timing for the code you ask about, and the answer then
uses the fastest traction recorded there, which makes it optimistic.
The CLI says how much of the answer that affects:

```console
$ bplan-geography time LEEDS SHEFFLD -d bplan -t 195
  note: only 89% of that is timed for traction 195; the rest falls back to the fastest recorded traction, so the figure is optimistic.
LEEDS -> SHEFFLD (traction 195): 37.5 min
```

In Python the same share comes from `running_time_detail`:

```python
minutes, exact_share = graph.running_time_detail("LEEDS", "SHEFFLD", "195")
# (37.5, 0.89)
```

An `exact_share` of 1.0 means every link on the route was timed for
that traction. The traction codes are BPLAN's own, listed in
`bplan_traction_loads.csv`; they are not always class numbers.

## How running times are worked out

Two stations a train calls at are usually not adjacent in BPLAN. The
train runs through intermediate timing points between them, so running
times are summed along a shortest path rather than looked up.

A calling train has to accelerate away from a stand and brake to one,
and BPLAN times those separately from passing at line speed (an entry
or exit speed of `0` against `-1`). The route is found using passing
times. Its first link then takes the start-from-stand timing, its last
link the stop timing, and a single-link journey takes the combined one.

Where several records exist for the same link and traction (different
running lines, or superseded variants), the fastest is kept. The graph
answers what is achievable: if any recorded variant is faster than a
proposed timing, the data alone cannot show that timing to be
infeasible.

Bus, ship, London Underground and Tyne and Wear Metro timings are left
out of the graph, because they are not trains on Network Rail track.
BPLAN has a bus timed from Brighton to North Wembley, and with it in
the graph a train from Brighton to Victoria came out at 35 minutes. The
excluded codes are in `bplan_geography.timing.NON_RAIL_TRACTION`, plus
anything starting `BUS`.

## What it reads

| Record | Holds | Written to |
|---|---|---|
| `LOC` | the TIPLOC register: name, OSGB easting and northing, STANOX | `bplan_locations.csv` |
| `NWK` | links between adjacent TIPLOCs: running line, direction, distance, route availability | `bplan_network_links.csv` |
| `TLK` | minimum sectional running times by traction and running line | `bplan_timing_links.csv` |
| `TLD` | traction and timing load definitions: maximum speed, description, category | `bplan_traction_loads.csv` |

`PLT` (platforms), `REF` (reference codes) and the other record types
make up most of the file. A prefix test skips them before any field is
split, which is why a 90 MB extract cleans in seconds.

## The field layout

The column positions were worked out from real extracts, not taken from
an interface specification. They have been cross-checked:

- the `LOC` eastings and northings for London Euston (`529500, 182700`)
  and Kings Cross (`530200, 183200`) match published OSGB grid
  references, and
- `NWK` and `TLK` values around Leeds and on the slow Aberdare branch
  give believable distances and speeds.

No specification has confirmed them, though. Records with too few
fields are skipped, counted and logged as a warning, so a change in
layout shows up instead of producing wrong columns.

## Limitations

- `BplanNetworkLinks.running_line_count()` is as close as BPLAN gets to
  saying a segment is multi-track. It is not a count of tracks or of
  platforms (platforms are in `PLT`, which is not parsed), and the
  running line labels have not been checked against a specification.
  It is useful context for someone looking at a possible headway
  conflict, but not a reason to dismiss one automatically.
- The timing graph is directed. A route one way does not mean there is
  one back.
- Records are not filtered by date. The fastest variant is used
  whatever its validity window.

## Python API

| Name | |
|---|---|
| `clean_extract(source, output_dir)` | write the four CSVs and return row counts |
| `BplanTimingGraph(cleaned_dir)` | the running time graph |
| `.minimum_running_time(from, to, traction)` | minutes, or `None` with no route |
| `.running_time_detail(from, to, traction)` | minutes and the exact traction share |
| `BplanNetworkLinks(cleaned_dir)` | running lines and distances between adjacent TIPLOCs |
| `read_header(path)` | the extract's validity window |
| `iter_records(path)` | stream `(record_type, fields)` for the kept types |
| `parse_srt_minutes("+04'30")` | `4.5` |

## Development

```sh
git clone https://github.com/rosedillon/bplan-geography
cd bplan-geography
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy src
```

The tests build small synthetic extracts with the same field layout as
the real thing (column positions, `+MM'SS` times, the entry and exit
speed convention), so the index constants are under test too. No
licensed data is committed.

## Licence

GPL-3.0. See [LICENSE](LICENSE).

Not affiliated with or endorsed by Network Rail.
