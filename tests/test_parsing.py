from __future__ import annotations

import csv
from typing import TYPE_CHECKING

import pytest

from bplan_geography import (
    OUTPUT_FILENAMES,
    clean_extract,
    iter_records,
    parse_srt_minutes,
    read_header,
)

if TYPE_CHECKING:
    import pathlib


class TestParseSrtMinutes:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("+04'00", 4.0),
            ("04'00", 4.0),
            ("+00'30", 0.5),
            ("+37'00", 37.0),
            ("+01'45", 1.75),
            ("-02'00", -2.0),
        ],
    )
    def test_valid(self, value: str, expected: float) -> None:
        assert parse_srt_minutes(value) == pytest.approx(expected)

    @pytest.mark.parametrize("value", ["", "   ", "4:00", "abc", "0400", "+04'"])
    def test_unparseable_returns_none(self, value: str) -> None:
        assert parse_srt_minutes(value) is None

    def test_surrounding_whitespace_tolerated(self) -> None:
        assert parse_srt_minutes("  +04'00  ") == 4.0


class TestHeader:
    def test_header_is_read(self, extract: pathlib.Path) -> None:
        header = read_header(extract)
        assert header is not None
        assert header.owner == "NR"
        assert header.valid_from is not None
        assert header.valid_from.year == 2026
        assert "2026-05-17" in header.description

    def test_no_header(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "trimmed.txt"
        path.write_text("LOC\tA\tAAAA\tAytown\n")
        assert read_header(path) is None


class TestIterRecords:
    def test_only_kept_record_types_are_yielded(self, extract: pathlib.Path) -> None:
        types = {record_type for record_type, _ in iter_records(extract)}
        assert types == {"LOC", "NWK", "TLK", "TLD"}

    def test_ignored_types_never_appear(self, extract: pathlib.Path) -> None:
        # REF, PLT and the PIF header are the bulk of a real file.
        for record_type, _ in iter_records(extract):
            assert record_type not in {"REF", "PLT", "PIF"}


class TestCleanExtract:
    def test_writes_one_csv_per_record_type(self, cleaned: pathlib.Path) -> None:
        for filename in OUTPUT_FILENAMES.values():
            assert (cleaned / filename).exists()

    def test_counts_match_the_rows_written(
        self, extract: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        output = tmp_path / "out"
        counts = clean_extract(extract, output)
        for record_type, filename in OUTPUT_FILENAMES.items():
            with (output / filename).open() as handle:
                rows = list(csv.DictReader(handle))
            assert len(rows) == counts[record_type], record_type

    def test_locations(self, cleaned: pathlib.Path) -> None:
        with (cleaned / OUTPUT_FILENAMES["LOC"]).open() as handle:
            rows = {row["tiploc"]: row for row in csv.DictReader(handle)}
        # Euston's real grid reference, used as a cross-check on the
        # indices.
        assert rows["AAAA"]["name"] == "Aytown"
        assert rows["AAAA"]["easting"] == "529500"
        assert rows["AAAA"]["northing"] == "182700"
        assert rows["AAAA"]["stanox"] == "00001"

    def test_short_record_skipped(self, cleaned: pathlib.Path) -> None:
        with (cleaned / OUTPUT_FILENAMES["LOC"]).open() as handle:
            tiplocs = {row["tiploc"] for row in csv.DictReader(handle)}
        assert "SHORT" not in tiplocs
        assert {"AAAA", "BBBB", "CCCC", "DDDD"} <= tiplocs

    def test_timing_links_convert_to_minutes(self, cleaned: pathlib.Path) -> None:
        with (cleaned / OUTPUT_FILENAMES["TLK"]).open() as handle:
            rows = list(csv.DictReader(handle))
        passing = [
            row
            for row in rows
            if row["from_tiploc"] == "BBBB"
            and row["to_tiploc"] == "CCCC"
            and row["entry_speed"] == "-1"
        ]
        assert passing
        assert float(passing[0]["sectional_running_time_minutes"]) == pytest.approx(3.0)

    def test_timing_link_without_time(self, cleaned: pathlib.Path) -> None:
        with (cleaned / OUTPUT_FILENAMES["TLK"]).open() as handle:
            pairs = {(row["from_tiploc"], row["to_tiploc"]) for row in csv.DictReader(handle)}
        assert ("CCCC", "DDDD") not in pairs

    def test_network_links(self, cleaned: pathlib.Path) -> None:
        with (cleaned / OUTPUT_FILENAMES["NWK"]).open() as handle:
            rows = list(csv.DictReader(handle))
        a_to_b = next(r for r in rows if (r["from_tiploc"], r["to_tiploc"]) == ("AAAA", "BBBB"))
        assert a_to_b["distance_metres"] == "02000"
        assert a_to_b["route_availability"] == "4"

    def test_traction_definitions_parse(self, cleaned: pathlib.Path) -> None:
        with (cleaned / OUTPUT_FILENAMES["TLD"]).open() as handle:
            rows = {row["traction_code"]: row for row in csv.DictReader(handle)}
        assert rows["185"]["description"] == "Class 185 Desiro"
        assert rows["185"]["max_speed_mph"] == "100"

    def test_output_directory_is_created(
        self, extract: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        nested = tmp_path / "does" / "not" / "exist"
        clean_extract(extract, nested)
        assert (nested / OUTPUT_FILENAMES["LOC"]).exists()

    def test_empty_extract_writes_headers(self, tmp_path: pathlib.Path) -> None:
        source = tmp_path / "only-ref.txt"
        source.write_text("REF\tA\tACC\t \tUndefined\n")
        counts = clean_extract(source, tmp_path / "out")
        assert counts == {"LOC": 0, "NWK": 0, "TLK": 0, "TLD": 0}
        with (tmp_path / "out" / OUTPUT_FILENAMES["LOC"]).open() as handle:
            assert next(csv.reader(handle)) == ["tiploc", "name", "easting", "northing", "stanox"]
