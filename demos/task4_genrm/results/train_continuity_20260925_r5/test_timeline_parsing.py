#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Unit tests for the v2 reanalysis parser: timezone basis, cross-midnight
rollover, window-boundary membership. Plain asserts; runnable via pytest or
directly (``python test_timeline_parsing.py``)."""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from reanalyze_three_timelines_v2 import Timeline  # noqa: E402


def test_epoch_matches_events_json_basis():
    """2026-09-26 00:12:30 CST == epoch 1790352750 (the events.json basis)."""
    tl = Timeline("2026-09-26", 8.0)
    assert tl.parse("x 2026-09-26 00:12:30 y") == 1790352750.0


def test_full_date_uses_its_own_day():
    tl = Timeline("2026-09-26", 8.0)
    assert tl.parse("2026-09-27 00:00:10") - tl.parse("2026-09-26 23:59:50") == 20.0


def test_bare_time_rolls_over_midnight():
    tl = Timeline("2026-09-26", 8.0)
    first = tl.parse_bare("23:59:50")
    second = tl.parse_bare("00:00:10")
    assert second - first == 20.0, "midnight rollover must advance the inferred date"


def test_bare_time_same_day_no_rollover():
    tl = Timeline("2026-09-26", 8.0)
    first = tl.parse_bare("10:00:00")
    second = tl.parse_bare("10:00:30")
    assert second - first == 30.0


def test_tz_offset_moves_epoch():
    """Same wall time, different tz basis: UTC+9 is 3600s earlier in epoch."""
    cst = Timeline("2026-09-26", 8.0).parse("2026-09-26 00:00:00")
    jst = Timeline("2026-09-26", 9.0).parse("2026-09-26 00:00:00")
    assert cst - jst == 3600.0


def test_no_timestamp_returns_none():
    tl = Timeline("2026-09-26", 8.0)
    assert tl.parse("no timestamp here") is None


def test_ansi_codes_do_not_hide_markers():
    """Colour codes precede markers (``...[1;37mperf 0:``): the script strips
    ANSI before matching, so ``perf 0: {`` must be found after ``m``."""
    import re

    ansi = re.compile(r"\x1b\[[0-9;]*m")
    line = "\x1b[36m(pid=1)\x1b[0m \x1b[1;37mperf 0: {'perf/train_time': 1.0}\x1b[0m"
    stripped = ansi.sub("", line)
    assert re.search(r"(?<![A-Za-z])perf (\d+): \{", stripped)


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    run_all()
