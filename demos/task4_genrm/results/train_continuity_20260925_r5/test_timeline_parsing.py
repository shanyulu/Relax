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


# --- renderer v2.1: boundary crossings are computed, never asserted ----------------------

import render_reanalysis_v2 as rr  # noqa: E402

_WINDOWS = [
    {"window": "scale_out_execution", "start_epoch": 2753.635, "end_epoch": 2812.411},
    {"window": "dual_replica_stable", "start_epoch": 2812.411, "end_epoch": 2857.574},
    {"window": "scale_in_execution", "start_epoch": 2857.574, "end_epoch": 2858.6},
]


def test_epoch_pairs_sorts_dict_and_list_epochs():
    assert rr.epoch_pairs({"b": 20.0, "a": 10.0, "c": 30.0}) == [(10.0, 20.0), (20.0, 30.0)]
    assert rr.epoch_pairs([30.0, 10.0, 20.0]) == [(10.0, 20.0), (20.0, 30.0)]
    assert rr.epoch_pairs({"only": 1.0}) == []


def test_max_gap_interval_finds_largest_consecutive_gap():
    assert rr.max_gap_interval({"a": 10.0, "b": 30.0, "c": 33.0}) == (20.0, 10.0, 30.0)
    assert rr.max_gap_interval({}) is None


def test_boundaries_crossed_reports_contiguous_shared_epoch_once():
    """Scale-out end == stable start (2812.411): one entry, merged label."""
    crossed = rr.boundaries_crossed(2750.0, 2825.0, _WINDOWS)
    assert crossed == ["scale-out start", "scale-out end (= stable start)"]


def test_boundaries_crossed_none_when_interval_inside_a_window():
    assert rr.boundaries_crossed(2820.0, 2830.0, _WINDOWS) == []


def test_real_data_max_gaps_match_recomputed_review():
    """Reviewer-recomputed crossings from the committed epochs must reproduce:
    step-start 75 s spans scale-out; exec-end 29 s spans scale-in; rollout
    76 s crosses the scale-out completion boundary."""
    st = rr.R["step_timelines"]
    gap, _, _ = rr.max_gap_interval(st["step_start"]["epochs"])
    assert gap == 75.0
    crossed = rr.boundaries_crossed(*rr.max_gap_interval(st["step_start"]["epochs"])[1:], rr.R["windows"])
    assert any(c.startswith("scale-out start") for c in crossed)
    assert any(c.startswith("scale-out end") for c in crossed)

    gap, t0, t1 = rr.max_gap_interval(st["step_execution_end"]["epochs"])
    assert gap == 29.0
    crossed = rr.boundaries_crossed(t0, t1, rr.R["windows"])
    assert any(c.startswith("scale-in start") or "(= scale-in start)" in c for c in crossed)
    assert any(c.startswith("scale-in end") for c in crossed)

    gap, t0, t1 = rr.max_gap_interval(st["rollout_completed"]["epochs"])
    assert gap == 76.0
    crossed = rr.boundaries_crossed(t0, t1, rr.R["windows"])
    assert any(c.startswith("scale-out end") for c in crossed)
    assert not any(c.startswith("scale-out start") for c in crossed)


def test_fmt_np_shows_window_duration_for_empty_timelines():
    assert rr.fmt_np(23.0, 45.2) == "23.0 s"
    assert rr.fmt_np(None, 1.0) == "1.0 s (no in-window events)"


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    run_all()
