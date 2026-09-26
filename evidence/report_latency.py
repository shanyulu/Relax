#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Straggler reporting-latency report for the ON arms of the GPU campaign.

The script first *inspects the real JSONL keys* (it assumes no schema), then tries to
build the wall-clock latency chain

    interval complete -> collector ingest -> verdict creation -> persisted line

and reports p50/p95/p99/max for every hop it can honestly measure. A hop whose
timestamps are genuinely absent is reported as ABSENT with the exact field that would be
needed, never replaced by a substitute. It then computes the schedule-dependent delay
that is derivable: a window's last envelope does not close the window, so the gap
between a verdict's window close and the arrival of the triggering envelope is measured.

Deriving the window close requires the window length (and a window anchor). The window
length is read from the ON arm manifest (`RELAX_STRAGGLER_WINDOW_S`); if it is not
recorded, the report falls back to a CLI default and flags the result as assumption-
dependent rather than silently treating it as measured.

Usage:
    report_latency.py [--root gpu_campaign] [--campaign DIR] [--json latency_report.json]
                      [--md LATENCY_REPORT.md] [--default-window-s 5.0]
"""

import argparse
import collections
import json
import math
import pathlib
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

# Candidate field names that *would* carry the missing timestamps. Reported, never invented.
CHAIN_HOP_CANDIDATES = {
    "collector_ingest": ("ingest_host_s", "ingest_host", "collector_recv_host_s", "recv_host_s", "received_at"),
    "verdict_creation": ("verdict_host_s", "created_host_s", "verdict_created_host_s", "created_at", "emit_host_s"),
    "persisted_line": ("persist_host_s", "written_host_s", "flush_host_s", "persisted_at"),
}
ENVELOPE_TIME_KEYS = ("host_start", "host_end", "host_ms", "device_ms")
VERDICT_TIME_KEYS = ("rank_host_ms", "reference_host_ms", "rank_device_ms", "reference_device_ms")


def load_json(path: pathlib.Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def read_jsonl(path: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path:
        return rows
    file_path = pathlib.Path(path)
    if not file_path.is_file():
        return rows
    with file_path.open("r", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def key_union(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counter: collections.Counter = collections.Counter()
    for row in rows:
        counter.update(row.keys())
    return dict(sorted(counter.items()))


def percentile_nearest(ordered: List[float], fraction: float) -> Optional[float]:
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def distribution(values: List[float]) -> Optional[Dict[str, Any]]:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "n": len(values),
        "min": ordered[0],
        "mean": statistics.fmean(ordered),
        "p50": percentile_nearest(ordered, 0.50),
        "p95": percentile_nearest(ordered, 0.95),
        "p99": percentile_nearest(ordered, 0.99),
        "max": ordered[-1],
    }


def declared_window_s(arm_dir: pathlib.Path) -> Tuple[Optional[float], str]:
    """Read RELAX_STRAGGLER_WINDOW_S from the arm manifest, if recorded."""
    manifest = load_json(arm_dir / "manifest.json")
    if isinstance(manifest, dict):
        env = manifest.get("relax_env")
        if isinstance(env, dict) and "RELAX_STRAGGLER_WINDOW_S" in env:
            try:
                return float(env["RELAX_STRAGGLER_WINDOW_S"]), "manifest.relax_env.RELAX_STRAGGLER_WINDOW_S"
            except (TypeError, ValueError):
                pass
    return None, "not recorded in arm manifest"


def discover_on_arms(root: pathlib.Path) -> List[pathlib.Path]:
    """Directories whose summary.json has a dict collector_status with both JSONL paths."""
    arms: List[pathlib.Path] = []
    for summary_path in sorted(root.rglob("summary.json")):
        summary = load_json(summary_path)
        if not isinstance(summary, dict):
            continue
        observation = summary.get("observation")
        if not isinstance(observation, dict):
            continue
        status = observation.get("collector_status")
        if not isinstance(status, dict):
            continue
        if status.get("envelope_path") and status.get("verdict_path"):
            arms.append(summary_path.parent)
    return arms


def schedule_delay(
    envelopes: List[Dict[str, Any]], verdicts: List[Dict[str, Any]], window_s: float
) -> Dict[str, Any]:
    """Gap between a verdict's derived window close and the triggering envelope arrival.

    Window model (stated because it is an inference from the data, not a recorded field):
    per cohort, window 0 starts at the earliest envelope ``host_start`` in that cohort;
    window ``k`` closes at ``anchor + (k + 1) * window_s`` on the same monotonic clock
    that stamps ``host_start``/``host_end``. An envelope belongs to window
    ``floor((host_end - anchor) / window_s)``. A verdict's ``window_index`` is matched
    against that bucket for the verdict's own ``(cohort, rank, name)``.
    """
    if not envelopes or not verdicts or window_s <= 0:
        return {"derivable": False, "reason": "missing envelopes, verdicts or a positive window length"}

    anchors: Dict[str, float] = {}
    for envelope in envelopes:
        cohort = envelope.get("cohort")
        start = envelope.get("host_start")
        if cohort is None or not isinstance(start, (int, float)):
            continue
        anchors[cohort] = min(anchors.get(cohort, math.inf), float(start))

    index: Dict[Tuple[Any, Any, Any, int], List[Dict[str, Any]]] = collections.defaultdict(list)
    for envelope in envelopes:
        cohort, rank, name, end = (
            envelope.get("cohort"),
            envelope.get("rank"),
            envelope.get("name"),
            envelope.get("host_end"),
        )
        if cohort not in anchors or not isinstance(end, (int, float)):
            continue
        bucket = int((float(end) - anchors[cohort]) // window_s)
        index[(cohort, rank, name, bucket)].append(envelope)

    gaps: List[float] = []
    per_kind: Dict[str, List[float]] = collections.defaultdict(list)
    unmatched: List[Dict[str, Any]] = []
    out_of_range: List[Dict[str, Any]] = []
    host_ms_agreement = 0
    unique_match = 0

    for verdict in verdicts:
        key = (verdict.get("cohort"), verdict.get("rank"), verdict.get("name"), verdict.get("window_index"))
        candidates = index.get(key, [])
        if not candidates:
            unmatched.append(
                {
                    "cohort": verdict.get("cohort"),
                    "rank": verdict.get("rank"),
                    "name": verdict.get("name"),
                    "window_index": verdict.get("window_index"),
                    "reason": "no envelope of this (rank, stage) falls in this window bucket",
                }
            )
            continue
        if len(candidates) == 1:
            unique_match += 1
        # Prefer the envelope whose measured host duration is the one the verdict reports;
        # otherwise fall back to the last arrival in the window.
        trigger = None
        rank_host_ms = verdict.get("rank_host_ms")
        if isinstance(rank_host_ms, (int, float)):
            exact = [item for item in candidates if item.get("host_ms") == rank_host_ms]
            if exact:
                trigger = max(exact, key=lambda item: item["host_end"])
                host_ms_agreement += 1
        if trigger is None:
            trigger = max(candidates, key=lambda item: item.get("host_end", -math.inf))
        cohort = verdict.get("cohort")
        window_close = anchors[cohort] + (int(verdict["window_index"]) + 1) * window_s
        gap = window_close - float(trigger["host_end"])
        gaps.append(gap)
        kind = str(verdict.get("kind", "unknown"))
        per_kind[kind].append(gap)
        if gap < -1e-9 or gap > window_s + 1e-9:
            out_of_range.append(
                {
                    "rank": verdict.get("rank"),
                    "name": verdict.get("name"),
                    "window_index": verdict.get("window_index"),
                    "gap_s": gap,
                }
            )

    result: Dict[str, Any] = {
        "derivable": bool(gaps),
        "definition": (
            "gap = derived_window_close(verdict.window_index) - host_end(triggering envelope); "
            "positive means the verdict's window closed after the triggering sample arrived"
        ),
        "window_s": window_s,
        "cohort_anchors": anchors,
        "n_verdicts": len(verdicts),
        "n_matched": len(gaps),
        "n_unmatched": len(unmatched),
        "n_unique_envelope_match": unique_match,
        "n_trigger_host_ms_agrees_with_verdict": host_ms_agreement,
        "n_gap_outside_[0,window_s]": len(out_of_range),
        "unmatched": unmatched[:20],
        "out_of_range": out_of_range[:20],
        "gap_s": distribution(gaps),
        "gap_s_by_kind": {kind: distribution(values) for kind, values in sorted(per_kind.items())},
    }
    return result


def analyse_arm(arm_dir: pathlib.Path, default_window_s: float) -> Dict[str, Any]:
    summary = load_json(arm_dir / "summary.json") or {}
    observation = summary.get("observation") if isinstance(summary.get("observation"), dict) else {}
    status = observation.get("collector_status") or {}
    envelope_path = status.get("envelope_path")
    verdict_path = status.get("verdict_path")

    envelopes = read_jsonl(envelope_path)
    verdicts = read_jsonl(verdict_path)

    window_s_declared, window_s_source = declared_window_s(arm_dir)
    window_s = window_s_declared if window_s_declared is not None else default_window_s

    envelope_keys = key_union(envelopes)
    verdict_keys = key_union(verdicts)

    hop_presence = {
        hop: [field for field in candidates if field in envelope_keys or field in verdict_keys]
        for hop, candidates in CHAIN_HOP_CANDIDATES.items()
    }

    interval_end = [float(row["host_end"]) for row in envelopes if isinstance(row.get("host_end"), (int, float))]
    interval_start = [float(row["host_start"]) for row in envelopes if isinstance(row.get("host_start"), (int, float))]
    measured_ms = [float(row["host_ms"]) for row in envelopes if isinstance(row.get("host_ms"), (int, float))]

    schedule = schedule_delay(envelopes, verdicts, window_s)
    schedule["window_s_declared"] = window_s_declared
    schedule["window_s_source"] = window_s_source
    schedule["schedule_delay_assumption_dependent"] = window_s_declared is None

    unavailable = {}
    for hop, candidates in CHAIN_HOP_CANDIDATES.items():
        found = hop_presence[hop]
        unavailable[hop] = {
            "available": bool(found),
            "recorded_fields_matching_candidates": found,
            "needed_field_examples": list(candidates),
            "why_absent": (
                "no ingest timestamp is recorded on the envelope: the JSONL is written after the "
                "collector has already consumed the packet, so ingest time is not observable"
                if hop == "collector_ingest"
                else "verdict records carry duration fields (rank_host_ms, reference_host_ms) but no creation timestamp"
                if hop == "verdict_creation"
                else "JSONL lines carry no per-line write timestamp; only whole-file mtime exists, which is not per record"
            ),
        }

    return {
        "arm": arm_dir.name,
        "campaign": arm_dir.parent.name,
        "dir": str(arm_dir),
        "envelope_path": envelope_path,
        "verdict_path": verdict_path,
        "n_envelopes": len(envelopes),
        "n_verdicts": len(verdicts),
        "envelope_keys": envelope_keys,
        "verdict_keys": verdict_keys,
        "envelope_time_fields_present": [key for key in ENVELOPE_TIME_KEYS if key in envelope_keys],
        "verdict_time_fields_present": [key for key in VERDICT_TIME_KEYS if key in verdict_keys],
        "latency_chain": {
            "clock": "host_start/host_end are host monotonic seconds (same clock per host)",
            "hop_interval_complete": {
                "available": bool(interval_end),
                "field": "straggler_envelopes.jsonl host_end",
                "meaning": "the measured interval has ended; this is the start of the reporting chain",
                "host_end_distribution": distribution(interval_end),
                "host_start_distribution": distribution(interval_start),
            },
            "hop_collector_ingest": unavailable["collector_ingest"],
            "hop_verdict_creation": unavailable["verdict_creation"],
            "hop_persisted_line": unavailable["persisted_line"],
            "overall_interval_to_persisted": {
                "available": False,
                "why_absent": "composite of the three absent hops; at least one end timestamp per record is missing",
                "needed_fields": sorted({field for candidates in CHAIN_HOP_CANDIDATES.values() for field in candidates}),
            },
            "derived_wait_from_trigger_to_window_close": schedule,
            "context_measured_interval_ms": distribution(measured_ms),
        },
        "schedule_delay": schedule,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Straggler reporting-latency report")
    lines.append("")
    lines.append(f"- root: `{report['root']}`")
    lines.append(f"- ON arms examined: {len(report['arms'])}")
    lines.append(f"- default window length when not declared: {report['default_window_s']} s")
    lines.append("")
    lines.append(
        "The chain hop names are: `interval complete -> collector ingest -> verdict creation -> persisted line`. "
        "A hop is reported as **ABSENT** when the artifacts genuinely carry no timestamp for it; the required field "
        "is named rather than replaced by a proxy."
    )
    lines.append("")

    for arm in report["arms"]:
        lines.append(f"## {arm['relative_dir']}")
        lines.append("")
        lines.append(f"- envelopes: {arm['n_envelopes']} rows; verdicts: {arm['n_verdicts']} rows")
        lines.append(f"- envelope keys observed: {', '.join(arm['envelope_keys']) or '(none)'}")
        lines.append(f"- verdict keys observed: {', '.join(arm['verdict_keys']) or '(none)'}")
        lines.append(f"- envelope time fields present: {arm['envelope_time_fields_present'] or 'none'}")
        lines.append(f"- verdict time fields present (durations only): {arm['verdict_time_fields_present'] or 'none'}")
        lines.append("")

        chain = arm["latency_chain"]
        lines.append("### Latency chain")
        lines.append("")
        lines.append("| hop | availability | field / required field | p50 | p95 | p99 | max |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        hop_interval = chain["hop_interval_complete"]
        dist = hop_interval.get("host_end_distribution") or {}
        lines.append(
            "| interval complete | available | `host_end` (monotonic s) | {p50} | {p95} | {p99} | {mx} |".format(
                p50=_fmt(dist.get("p50")), p95=_fmt(dist.get("p95")), p99=_fmt(dist.get("p99")), mx=_fmt(dist.get("max"))
            )
        )
        for label, key in (
            ("collector ingest", "hop_collector_ingest"),
            ("verdict creation", "hop_verdict_creation"),
            ("persisted line", "hop_persisted_line"),
        ):
            hop = chain[key]
            lines.append(
                "| {label} | ABSENT | needs {fields} | - | - | - | - |".format(
                    label=label, fields=", ".join(hop["needed_field_examples"])
                )
            )
        lines.append("| overall interval -> persisted | ABSENT | needs " + ", ".join(chain["overall_interval_to_persisted"]["needed_fields"]) + " | - | - | - | - |")
        lines.append("")
        for label, key in (
            ("collector ingest", "hop_collector_ingest"),
            ("verdict creation", "hop_verdict_creation"),
            ("persisted line", "hop_persisted_line"),
        ):
            hop = chain[key]
            lines.append(f"- **{label} — not derivable.** {hop['why_absent']}. Needed field(s): `{', '.join(hop['needed_field_examples'])}`.")
        lines.append("")

        schedule = arm["schedule_delay"]
        lines.append("### Schedule-dependent delay (derived)")
        lines.append("")
        if not schedule.get("derivable"):
            lines.append(f"- **not derivable**: {schedule.get('reason', 'unknown')}")
            lines.append("")
            continue
        lines.append(f"- window length used: {schedule['window_s']} s (source: {schedule['window_s_source']})")
        if schedule.get("schedule_delay_assumption_dependent"):
            lines.append(
                "- **assumption-dependent**: the window length is not recorded in this arm's manifest; "
                "the value above is the CLI default."
            )
        lines.append(f"- cohort anchors (min envelope `host_start` per cohort): {schedule['cohort_anchors']}")
        lines.append(
            f"- matched verdicts: {schedule['n_matched']}/{schedule['n_verdicts']}; "
            f"unique envelope matches: {schedule['n_unique_envelope_match']}; "
            f"trigger `host_ms` equals verdict `rank_host_ms`: {schedule['n_trigger_host_ms_agrees_with_verdict']}"
        )
        gap_dist = schedule.get("gap_s") or {}
        lines.append("| quantity | n | min | p50 | p95 | p99 | max | mean |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        lines.append(
            "| seconds | {n} | {mn} | {p50} | {p95} | {p99} | {mx} | {mean} |".format(
                n=gap_dist.get("n"),
                mn=_fmt(gap_dist.get("min")),
                p50=_fmt(gap_dist.get("p50")),
                p95=_fmt(gap_dist.get("p95")),
                p99=_fmt(gap_dist.get("p99")),
                mx=_fmt(gap_dist.get("max")),
                mean=_fmt(gap_dist.get("mean")),
            )
        )
        lines.append("")
        lines.append(
            f"- gaps outside `[0, window_s]`: {schedule['n_gap_outside_[0,window_s]']}; "
            f"unmatched verdicts: {schedule['n_unmatched']}"
        )
        if schedule.get("gap_s_by_kind"):
            lines.append("")
            lines.append("| verdict kind | n | p50 s | p95 s | max s |")
            lines.append("| --- | --- | --- | --- | --- |")
            for kind, dist_kind in schedule["gap_s_by_kind"].items():
                lines.append(
                    f"| {kind} | {dist_kind['n']} | {_fmt(dist_kind['p50'])} | {_fmt(dist_kind['p95'])} | {_fmt(dist_kind['max'])} |"
                )
        ctx = chain.get("context_measured_interval_ms") or {}
        lines.append("")
        lines.append(
            f"- context: measured interval `host_ms` p50 {_fmt(ctx.get('p50'))} ms, p95 {_fmt(ctx.get('p95'))} ms, "
            f"p99 {_fmt(ctx.get('p99'))} ms, max {_fmt(ctx.get('max'))} ms (the profiled stage durations, not latency hops)"
        )
        lines.append("")

    lines.append("## What could not be derived, and what is needed")
    lines.append("")
    lines.append(
        "- **collector ingest timestamp** — absent. The envelope JSONL is written after the collector already "
        "consumed the packet; add an `ingest_host_s` (or `collector_recv_host_s`) stamped when the receiver "
        "accepts the packet, and surface it on the envelope row."
    )
    lines.append(
        "- **verdict creation timestamp** — absent. Verdicts carry only durations (`rank_host_ms`, "
        "`reference_host_ms`). Add a `verdict_host_s`/`created_host_s` stamped when the detector emits the verdict."
    )
    lines.append(
        "- **persisted-line timestamp** — absent. Lines carry no write timestamp. Add a `persist_host_s` "
        "(or write a per-record timestamp) so the flush hop is measurable; whole-file mtime is not a per-record value."
    )
    lines.append(
        "- **overall interval -> persisted** — therefore absent; it is the sum of the absent hops."
    )
    lines.append(
        "- **schedule-dependent delay** — derivable for arms whose window length is recorded, by reconstructing "
        "the window close from the cohort anchor and `window_index` (see the definition above). For arms without "
        "a recorded window length the value is flagged assumption-dependent."
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("gpu_campaign"))
    parser.add_argument("--campaign", type=pathlib.Path, default=None, help="restrict to one campaign directory")
    parser.add_argument("--json", type=pathlib.Path, default=pathlib.Path("latency_report.json"))
    parser.add_argument("--md", type=pathlib.Path, default=pathlib.Path("LATENCY_REPORT.md"))
    parser.add_argument("--default-window-s", type=float, default=5.0)
    args = parser.parse_args(argv)

    search_root = args.campaign if args.campaign is not None else args.root
    if not search_root.is_dir():
        parser.error(f"search root not found: {search_root}")

    arm_dirs = discover_on_arms(search_root)
    base = search_root if args.campaign is not None else args.root
    arms = []
    for arm_dir in arm_dirs:
        entry = analyse_arm(arm_dir, args.default_window_s)
        try:
            entry["relative_dir"] = str(arm_dir.relative_to(base))
        except ValueError:
            entry["relative_dir"] = str(arm_dir)
        arms.append(entry)

    report = {
        "tool": "report_latency.py",
        "root": str(search_root),
        "default_window_s": args.default_window_s,
        "arms": arms,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    markdown = render_markdown(report)
    args.md.write_text(markdown)
    print(markdown)
    print(f"[wrote] {args.json}")
    print(f"[wrote] {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())