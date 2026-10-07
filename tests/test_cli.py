from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from bplan_geography import cli
from bplan_geography.cli import build_parser

from .conftest import FAST_TRACTION, SLOW_TRACTION

if TYPE_CHECKING:
    import pathlib

    from _pytest.capture import CaptureFixture


SMOKE_ARGS = ["time", "AAAA", "BBBB"]


class TestClean:
    def test_reports_counts_per_record_type(
        self, extract: pathlib.Path, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        out_dir = tmp_path / "out"
        assert cli.main(["clean", str(extract), "-o", str(out_dir)]) == 0
        out = capsys.readouterr().out
        assert "LOC" in out
        assert "bplan_locations.csv" in out

    def test_json_output(
        self, extract: pathlib.Path, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["clean", str(extract), "-o", str(tmp_path / "out"), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["LOC"] == 4
        assert payload["TLD"] == 2

    def test_header_is_reported(
        self, extract: pathlib.Path, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["clean", str(extract), "-o", str(tmp_path / "out")]) == 0
        assert "NR extract" in capsys.readouterr().err

    def test_missing_source_is_an_error(
        self, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["clean", str(tmp_path / "nope.txt")]) == 1
        assert "not found" in capsys.readouterr().err

    def test_no_timing_links_warns(
        self, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        source = tmp_path / "no-tlk.txt"
        source.write_text("REF\tA\tACC\t \tUndefined\n")
        assert cli.main(["clean", str(source), "-o", str(tmp_path / "out")]) == 0
        assert "timing graph would be empty" in capsys.readouterr().err


class TestTime:
    def test_reports_minutes(self, cleaned: pathlib.Path, capsys: CaptureFixture[str]) -> None:
        exit_code = cli.main(["time", "AAAA", "CCCC", "-d", str(cleaned), "-t", FAST_TRACTION])
        assert exit_code == 0
        assert "5.5 min" in capsys.readouterr().out

    def test_json_carries_the_exact_share(
        self, cleaned: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(
            ["time", "AAAA", "CCCC", "-d", str(cleaned), "-t", FAST_TRACTION, "--json"]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["minutes"] == pytest.approx(5.5)
        assert payload["exact_traction_share"] == pytest.approx(1.0)

    def test_partial_traction(self, cleaned: pathlib.Path, capsys: CaptureFixture[str]) -> None:
        exit_code = cli.main(["time", "AAAA", "CCCC", "-d", str(cleaned), "-t", SLOW_TRACTION])
        assert exit_code == 0
        assert "optimistic" in capsys.readouterr().err

    def test_unknown_tiploc(self, cleaned: pathlib.Path, capsys: CaptureFixture[str]) -> None:
        assert cli.main(["time", "ZZZZ", "AAAA", "-d", str(cleaned)]) == 1
        assert "ZZZZ" in capsys.readouterr().err

    def test_uncleaned_directory(
        self, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["time", "AAAA", "BBBB", "-d", str(tmp_path)]) == 1
        assert "Run `bplan-geography clean" in capsys.readouterr().err


class TestLines:
    def test_reports_running_lines_and_distance(
        self, cleaned: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["lines", "BBBB", "CCCC", "-d", str(cleaned)]) == 0
        out = capsys.readouterr().out
        assert "2" in out
        assert "3,000 m" in out

    def test_json_output(self, cleaned: pathlib.Path, capsys: CaptureFixture[str]) -> None:
        assert cli.main(["lines", "AAAA", "BBBB", "-d", str(cleaned), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["running_lines"] == 1
        assert payload["distance_metres"] == pytest.approx(2000.0)

    def test_non_adjacent_pair_is_an_error(
        self, cleaned: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["lines", "AAAA", "DDDD", "-d", str(cleaned)]) == 1
        assert "not be adjacent" in capsys.readouterr().err


def test_no_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code != 0


@pytest.mark.parametrize(
    ("argv", "verbose"),
    [(SMOKE_ARGS, False), (["-v", *SMOKE_ARGS], True), ([*SMOKE_ARGS, "-v"], True)],
)
def test_verbose_flag(argv: list[str], verbose: bool) -> None:
    assert build_parser().parse_args(argv).verbose is verbose
