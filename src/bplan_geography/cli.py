"""Command-line interface.

``clean`` turns an extract into CSVs. The other subcommands read those
CSVs back, so run ``clean`` first.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import TYPE_CHECKING

from bplan_geography.network import BplanNetworkLinks
from bplan_geography.parsing import OUTPUT_FILENAMES, clean_extract, read_header
from bplan_geography.timing import BplanTimingGraph

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def _require_cleaned(directory: pathlib.Path, record_type: str) -> int | None:
    expected = directory / OUTPUT_FILENAMES[record_type]
    if expected.exists():
        return None
    print(
        f"error: {expected} not found. "
        f"Run `bplan-geography clean <extract> -o {directory}` first.",
        file=sys.stderr,
    )
    return 1


def _cmd_clean(args: argparse.Namespace) -> int:
    if not args.source.exists():
        print(f"error: {args.source} not found", file=sys.stderr)
        return 1

    header = read_header(args.source)
    if header:
        print(header.description, file=sys.stderr)
    else:
        print(
            "note: no PIF header found; this may be a trimmed extract",
            file=sys.stderr,
        )

    counts = clean_extract(args.source, args.output)
    if args.json:
        json.dump(counts, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        width = max(len(name) for name in counts)
        for record_type, count in counts.items():
            print(f"{record_type:<{width}}  {count:>9,}  -> {OUTPUT_FILENAMES[record_type]}")
    if not counts.get("TLK"):
        print(
            "warning: no timing links parsed, so the timing graph would be empty",
            file=sys.stderr,
        )
    return 0


def _cmd_time(args: argparse.Namespace) -> int:
    failure = _require_cleaned(args.directory, "TLK")
    if failure is not None:
        return failure

    graph = BplanTimingGraph(args.directory)
    minutes, exact_share = graph.running_time_detail(args.origin, args.destination, args.traction)
    if minutes is None:
        missing = [
            tiploc
            for tiploc in (args.origin, args.destination)
            if tiploc.strip().upper() not in graph.graph
        ]
        reason = (
            f"{' and '.join(missing)} not in the timing graph"
            if missing
            else "no route between them in the timing data"
        )
        print(f"error: no running time available: {reason}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(
            {
                "from": args.origin.upper(),
                "to": args.destination.upper(),
                "traction": args.traction,
                "minutes": minutes,
                "exact_traction_share": exact_share,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    print(
        f"{args.origin.upper()} -> {args.destination.upper()} "
        f"(traction {args.traction}): {minutes:.1f} min"
    )
    if exact_share is not None and exact_share < 1.0:
        print(
            f"  note: only {exact_share:.0%} of that is timed for traction "
            f"{args.traction}; the rest falls back to the fastest recorded "
            "traction, so the figure is optimistic.",
            file=sys.stderr,
        )
    return 0


def _cmd_lines(args: argparse.Namespace) -> int:
    failure = _require_cleaned(args.directory, "NWK")
    if failure is not None:
        return failure

    links = BplanNetworkLinks(args.directory)
    count = links.running_line_count(args.origin, args.destination)
    metres = links.distance_metres(args.origin, args.destination)
    if count is None:
        print(
            f"error: no network link recorded from {args.origin.upper()} to "
            f"{args.destination.upper()} (they may not be adjacent)",
            file=sys.stderr,
        )
        return 1

    if args.json:
        json.dump(
            {
                "from": args.origin.upper(),
                "to": args.destination.upper(),
                "running_lines": count,
                "distance_metres": metres,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    print(f"{args.origin.upper()} -> {args.destination.upper()}")
    print(f"  distinct running lines  {count}")
    if metres is not None:
        print(f"  link distance           {metres:,.0f} m")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bplan-geography",
        description=(
            "Parse a Network Rail BPLAN Geography extract into CSVs, and query the "
            "resulting network topology and minimum sectional running times."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log progress")
    subparsers = parser.add_subparsers(dest="command", required=True)

    clean = subparsers.add_parser(
        "clean",
        help="Turn an extract into one CSV per record type.",
        description="Stream a BPLAN extract and write LOC/NWK/TLK/TLD CSVs.",
    )
    clean.add_argument("source", type=pathlib.Path, help="the BPLAN extract (.txt)")
    clean.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("bplan"),
        help="directory for the CSVs (default: ./bplan)",
    )
    clean.add_argument("--json", action="store_true", help="emit row counts as JSON")
    clean.set_defaults(func=_cmd_clean)

    time_cmd = subparsers.add_parser(
        "time",
        help="Minimum running time between two TIPLOCs.",
        description="Minimum achievable running time between two TIPLOCs, in minutes.",
    )
    time_cmd.add_argument("origin", help="origin TIPLOC")
    time_cmd.add_argument("destination", help="destination TIPLOC")
    time_cmd.add_argument(
        "-d",
        "--directory",
        type=pathlib.Path,
        default=pathlib.Path("bplan"),
        help="directory of cleaned CSVs (default: ./bplan)",
    )
    time_cmd.add_argument(
        "-t", "--traction", default="150", help="BPLAN traction code (default: 150)"
    )
    time_cmd.add_argument("--json", action="store_true", help="emit JSON")
    time_cmd.set_defaults(func=_cmd_time)

    lines = subparsers.add_parser(
        "lines",
        help="Running lines and distance between adjacent TIPLOCs.",
        description="Distinct running lines and link distance between two adjacent TIPLOCs.",
    )
    lines.add_argument("origin", help="origin TIPLOC")
    lines.add_argument("destination", help="destination TIPLOC")
    lines.add_argument(
        "-d",
        "--directory",
        type=pathlib.Path,
        default=pathlib.Path("bplan"),
        help="directory of cleaned CSVs (default: ./bplan)",
    )
    lines.add_argument("--json", action="store_true", help="emit JSON")
    lines.set_defaults(func=_cmd_lines)

    # -v also works after the subcommand.
    for subcommand in subparsers.choices.values():
        subcommand.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="log progress",
        )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    return int(args.func(args))
