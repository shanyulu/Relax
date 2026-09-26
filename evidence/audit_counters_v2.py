#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Machine audit of straggler counter provenance across every GPU campaign.

For every arm whose summary.json exposes a dict ``observation.collector_status`` this
script recomputes, from the raw artifacts:

  * the four-way ingest partition and whether it is conserved
    (judged + late + duplicate + invalid == envelopes);
  * the number of lines actually persisted in the recorded envelope/verdict JSONL files;
  * the LAST periodic ``straggler[...]: envelopes=... judged=... late=...`` line in the
    arm's job.log and whether its counters equal the final collector_status.

Nothing is hand-written: every number comes from summary.json, the JSONL files, or job.log.

Usage:
    audit_counters_v2.py [--root gpu_campaign] [--json counter_provenance_audit_v2.json]
                         [--md COUNTER_PROVENANCE_AUDIT_V2.md]
"""

import argparse
import json
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional

PERIODIC_RE = re.compile(r"straggler\[(?P<identity>[^\]]*)\]\s*:\s*(?P<rest>.*)$")
KV_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>[^\s]+)")

# Periodic-line counter name -> collector_status field name.
PERIODIC_TO_STATUS = {
    "envelopes": "envelopes",
    "judged": "judged_packets",
    "late": "late_packets",
    "duplicate": "duplicate_packets",
    "invalid": "invalid_packets",
    "verdicts": "verdicts",
    "windows": "windows_closed",
}
PROVENANCE_FIELDS = ("envelopes", "judged", "late", "duplicate", "invalid")


def count_lines(path: Optional[str]) -> Optional[int]:
    """Line-count a JSONL file, or None if the path is absent/unreadable."""
    if not path:
        return None
    file_path = pathlib.Path(path)
    if not file_path.is_file():
        return None
    with file_path.open("r", errors="replace") as handle:
        return sum(1 for _ in handle)


def load_json(path: pathlib.Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def collector_status_of(summary: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return None
    observation = summary.get("observation")
    if not isinstance(observation, dict):
        return None
    status = observation.get("collector_status")
    return status if isinstance(status, dict) else None


def last_periodic_line(job_log: pathlib.Path) -> Optional[Dict[str, Any]]:
    """Return the last periodic straggler[...] counter line in a job.log."""
    if not job_log.is_file():
        return None
    last: Optional[Dict[str, Any]] = None
    with job_log.open("r", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            match = PERIODIC_RE.search(line)
            if not match:
                continue
            fields: Dict[str, str] = {}
            for key, value in KV_RE.findall(match.group("rest")):
                try:
                    fields[key] = int(value)
                except ValueError:
                    fields[key] = value
            last = {
                "line_no": line_no,
                "identity": match.group("identity").strip(),
                "raw": line.rstrip("\n"),
                "fields": fields,
            }
    return last


def has_any_log(arm_dir: pathlib.Path) -> Dict[str, bool]:
    return {
        name: (arm_dir / name).is_file() for name in ("job.log", "submit.log", "off-smoke-submit.log")
    }


def audit_arm(arm_dir: pathlib.Path, campaign_root: pathlib.Path) -> Dict[str, Any]:
    summary = load_json(arm_dir / "summary.json")
    status = collector_status_of(summary) or {}

    envelopes = status.get("envelopes")
    judged = status.get("judged_packets")
    late = status.get("late_packets")
    duplicate = status.get("duplicate_packets")
    invalid = status.get("invalid_packets")

    numeric = [envelopes, judged, late, duplicate, invalid]
    # Conservation: judged + late + duplicate + invalid == envelopes. `envelopes` is the
    # total being partitioned, so it is excluded from the sum itself.
    partition_fields = [judged, late, duplicate, invalid]
    partition_sum = sum(value for value in partition_fields if isinstance(value, int))
    conservation_known = all(isinstance(value, int) for value in numeric)
    conserved = bool(conservation_known and partition_sum == envelopes)

    envelope_path = status.get("envelope_path")
    verdict_path = status.get("verdict_path")
    persisted_envelopes = count_lines(envelope_path)
    persisted_verdicts = count_lines(verdict_path)

    drops = partition_sum - (envelopes if isinstance(envelopes, int) else 0) if conservation_known else None
    expected_envelope_lines = envelopes - late - duplicate - invalid if all(
        isinstance(value, int) for value in (envelopes, late, duplicate, invalid)
    ) else None

    periodic = last_periodic_line(arm_dir / "job.log")
    periodic_block: Dict[str, Any] = {
        "present": periodic is not None,
        "job_log_present": (arm_dir / "job.log").is_file(),
        "other_logs": has_any_log(arm_dir),
    }
    if periodic is not None:
        comparisons: Dict[str, Any] = {}
        discrepancies: List[str] = []
        for line_key, status_key in PERIODIC_TO_STATUS.items():
            if line_key not in periodic["fields"]:
                continue
            line_value = periodic["fields"][line_key]
            status_value = status.get(status_key)
            match = line_value == status_value
            comparisons[line_key] = {
                "line_value": line_value,
                "collector_status_field": status_key,
                "collector_status_value": status_value,
                "match": match,
            }
            if not match:
                discrepancies.append(f"{line_key}={line_value} vs {status_key}={status_value}")
        # Provenance counters gate "the periodic line proves the final status"; verdicts /
        # windows are auxiliary and reported separately.
        provenance_keys = ("envelopes", "judged", "late", "duplicate", "invalid")
        provenance_match = all(
            comparisons.get(key, {}).get("match", True) for key in provenance_keys
        )
        all_match = all(comparison["match"] for comparison in comparisons.values())
        periodic_block.update(
            {
                "line_no": periodic["line_no"],
                "identity": periodic["identity"],
                "raw": periodic["raw"],
                "fields": periodic["fields"],
                "comparisons": comparisons,
                "provenance_counters_match": provenance_match,
                "all_counters_match": all_match,
                "discrepancies": discrepancies,
                "matches_final_status": provenance_match,
            }
        )

    return {
        "arm": arm_dir.name,
        "campaign": arm_dir.parent.name,
        "relative_dir": str(arm_dir.relative_to(campaign_root)),
        "dir": str(arm_dir),
        "envelopes": envelopes,
        "judged": judged,
        "late": late,
        "duplicate": duplicate,
        "invalid": invalid,
        "partition_sum": partition_sum,
        "conservation_known": conservation_known,
        "conserved": conserved,
        "conservation_detail": f"{judged} + {late} + {duplicate} + {invalid} = {partition_sum} vs envelopes={envelopes}",
        "persisted_envelope_lines": persisted_envelopes,
        "persisted_verdict_lines": persisted_verdicts,
        "envelope_path": envelope_path,
        "verdict_path": verdict_path,
        "envelope_path_exists": bool(envelope_path) and pathlib.Path(envelope_path).is_file(),
        "verdict_path_exists": bool(verdict_path) and pathlib.Path(verdict_path).is_file(),
        "expected_envelope_lines_if_drops_not_persisted": expected_envelope_lines,
        "persisted_envelope_lines_match_judged": persisted_envelopes == judged if isinstance(judged, int) else None,
        "persisted_envelope_lines_match_expected": (
            persisted_envelopes == expected_envelope_lines if expected_envelope_lines is not None else None
        ),
        "verdicts": status.get("verdicts"),
        "persisted_verdict_lines_match_verdicts": (
            persisted_verdicts == status.get("verdicts") if isinstance(status.get("verdicts"), int) else None
        ),
        "windows_closed": status.get("windows_closed"),
        "flushed_lines": status.get("flushed_lines"),
        "flushed_lines_match_persisted_total": (
            status.get("flushed_lines") == (persisted_envelopes or 0) + (persisted_verdicts or 0)
            if all(isinstance(value, int) for value in (status.get("flushed_lines"), persisted_envelopes, persisted_verdicts))
            else None
        ),
        "drops_between_ingest_and_persist": drops,
        "periodic": periodic_block,
    }


def discover_arms(root: pathlib.Path) -> List[pathlib.Path]:
    """Every directory under root that has a summary.json."""
    return sorted({path.parent for path in root.rglob("summary.json")})


def build_report(root: pathlib.Path) -> Dict[str, Any]:
    arms: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for arm_dir in discover_arms(root):
        summary = load_json(arm_dir / "summary.json")
        status = collector_status_of(summary)
        if status is None:
            observation = summary.get("observation") if isinstance(summary, dict) else None
            raw = observation.get("collector_status") if isinstance(observation, dict) else None
            skipped.append(
                {
                    "relative_dir": str(arm_dir.relative_to(root)),
                    "collector_status_kind": type(raw).__name__ if raw is not None else "absent",
                }
            )
            continue
        arms.append(audit_arm(arm_dir, root))

    violations = [arm["relative_dir"] for arm in arms if not arm["conserved"]]
    known = [arm for arm in arms if arm["conservation_known"]]
    periodic_present = [arm for arm in arms if arm["periodic"]["present"]]
    periodic_match = [arm for arm in periodic_present if arm["periodic"].get("provenance_counters_match")]
    periodic_all_match = [arm for arm in periodic_present if arm["periodic"].get("all_counters_match")]
    periodic_mismatch = [
        arm for arm in periodic_present if not arm["periodic"].get("provenance_counters_match")
    ]
    periodic_aux_mismatch = [
        arm for arm in periodic_present if arm["periodic"].get("provenance_counters_match") and not arm["periodic"].get("all_counters_match")
    ]
    summary_block = {
        "root": str(root),
        "n_arms_scanned": len(arms) + len(skipped),
        "n_arms_with_dict_collector_status": len(arms),
        "n_arms_skipped_non_dict_status": len(skipped),
        "n_conservation_evaluable": len(known),
        "n_conserved": len(known) - len(violations),
        "n_conservation_violations": len(violations),
        "conservation_violations": violations,
        "all_conserved": len(violations) == 0 and len(known) == len(arms),
        "n_periodic_line_present": len(periodic_present),
        "n_periodic_provenance_counters_match": len(periodic_match),
        "n_periodic_provenance_counters_mismatch": len(periodic_mismatch),
        "periodic_mismatch_arms": [arm["relative_dir"] for arm in periodic_mismatch],
        "n_periodic_all_counters_match": len(periodic_all_match),
        "n_periodic_aux_counters_mismatch": len(periodic_aux_mismatch),
        "periodic_aux_mismatch_arms": [arm["relative_dir"] for arm in periodic_aux_mismatch],
        "n_persisted_env_matches_judged": sum(
            1 for arm in arms if arm["persisted_envelope_lines_match_judged"]
        ),
        "n_persisted_verdict_matches_verdicts": sum(
            1 for arm in arms if arm["persisted_verdict_lines_match_verdicts"]
        ),
    }
    return {"tool": "audit_counters_v2.py", "arms": arms, "skipped": skipped, "summary": summary_block}


def render_markdown(report: Dict[str, Any]) -> str:
    summary = report["summary"]
    lines: List[str] = []
    lines.append("# Counter provenance audit (v2)")
    lines.append("")
    lines.append(f"- root scanned: `{summary['root']}`")
    lines.append(f"- summary.json files scanned: {summary['n_arms_scanned']}")
    lines.append(f"- arms with a dict `observation.collector_status`: {summary['n_arms_with_dict_collector_status']}")
    lines.append(f"- arms skipped (non-dict/absent collector_status): {summary['n_arms_skipped_non_dict_status']}")
    lines.append(
        f"- conservation `judged + late + duplicate + invalid == envelopes`: "
        f"{summary['n_conserved']}/{summary['n_conservation_evaluable']} conserved, "
        f"{summary['n_conservation_violations']} violation(s)"
    )
    lines.append(f"- **all conserved: {str(summary['all_conserved']).lower()}**")
    lines.append(
        f"- periodic last-line provenance counters (envelopes/judged/late/duplicate/invalid): "
        f"{summary['n_periodic_provenance_counters_match']} match, "
        f"{summary['n_periodic_provenance_counters_mismatch']} mismatch, "
        f"{summary['n_periodic_line_present']} periodic line(s) present of "
        f"{summary['n_arms_with_dict_collector_status']} arms"
    )
    lines.append(
        f"- periodic last-line ALL comparable counters (adds verdicts/windows_closed): "
        f"{summary['n_periodic_all_counters_match']} full match, "
        f"{summary['n_periodic_aux_counters_mismatch']} provenance-match-but-auxiliary-mismatch"
    )
    if summary["periodic_aux_mismatch_arms"]:
        lines.append(
            "- auxiliary-only mismatches: " + ", ".join(summary["periodic_aux_mismatch_arms"])
        )
    if summary["periodic_mismatch_arms"]:
        lines.append(
            "- **provenance mismatches**: " + ", ".join(summary["periodic_mismatch_arms"])
        )
    lines.append("")
    lines.append("## Per-arm provenance")
    lines.append("")
    lines.append(
        "| arm | envelopes | judged | late | duplicate | invalid | conserved | persisted_envelope_lines | persisted_verdict_lines |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for arm in report["arms"]:
        lines.append(
            "| {rel} | {env} | {judged} | {late} | {dup} | {invalid} | {cons} | {pe} | {pv} |".format(
                rel=arm["relative_dir"],
                env=arm["envelopes"],
                judged=arm["judged"],
                late=arm["late"],
                dup=arm["duplicate"],
                invalid=arm["invalid"],
                cons=str(arm["conserved"]).lower(),
                pe=arm["persisted_envelope_lines"],
                pv=arm["persisted_verdict_lines"],
            )
        )
    if not report["arms"]:
        lines.append("| (none) | - | - | - | - | - | - | - | - |")
    lines.append("")

    lines.append("## Conservation detail and derived relations")
    lines.append("")
    lines.append(
        "| arm | conservation equation | persisted_env == judged | persisted_env == envelopes-late-dup-invalid | "
        "persisted_verdict == verdicts | flushed_lines == persisted_env+verdicts |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for arm in report["arms"]:
        lines.append(
            "| {rel} | `{eq}` | {a} | {b} | {c} | {d} |".format(
                rel=arm["relative_dir"],
                eq=arm["conservation_detail"],
                a=_tri(arm["persisted_envelope_lines_match_judged"]),
                b=_tri(arm["persisted_envelope_lines_match_expected"]),
                c=_tri(arm["persisted_verdict_lines_match_verdicts"]),
                d=_tri(arm["flushed_lines_match_persisted_total"]),
            )
        )
    lines.append("")

    lines.append("## Periodic straggler[...] line vs final collector_status")
    lines.append("")
    for arm in report["arms"]:
        periodic = arm["periodic"]
        lines.append(f"### {arm['relative_dir']}")
        lines.append("")
        if not periodic["present"]:
            lines.append(
                f"- no periodic `straggler[...]` line found (job.log present: "
                f"{str(periodic['job_log_present']).lower()}; other logs: {periodic['other_logs']})"
            )
            lines.append("")
            continue
        lines.append(f"- last periodic line: job.log line {periodic['line_no']}, identity `{periodic['identity']}`")
        lines.append(f"- raw: `{periodic['raw'].strip()[:400]}`")
        lines.append("")
        lines.append("| periodic field | line value | collector_status field | collector_status value | match |")
        lines.append("| --- | --- | --- | --- | --- |")
        for line_key, comparison in periodic["comparisons"].items():
            lines.append(
                "| {k} | {lv} | {sk} | {sv} | {m} |".format(
                    k=line_key,
                    lv=comparison["line_value"],
                    sk=comparison["collector_status_field"],
                    sv=comparison["collector_status_value"],
                    m=_tri(comparison["match"]),
                )
            )
        lines.append("")
        if periodic["discrepancies"]:
            lines.append(f"- **discrepancy**: {'; '.join(periodic['discrepancies'])}")
        elif periodic.get("all_counters_match"):
            lines.append("- exact match on every comparable counter in the periodic line.")
        else:
            lines.append("- exact match on the provenance counters (envelopes/judged/late/duplicate/invalid).")
        lines.append("")

    lines.append("## Arms skipped (no dict collector_status)")
    lines.append("")
    for item in report["skipped"]:
        lines.append(f"- `{item['relative_dir']}`: collector_status kind = {item['collector_status_kind']}")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if summary["all_conserved"]:
        lines.append("Conservation holds everywhere that it is evaluable. No hand-written counters.")
    else:
        lines.append(
            "**Conservation VIOLATIONS present** in: " + ", ".join(summary["conservation_violations"]) + "."
        )
    return "\n".join(lines) + "\n"


def _tri(value: Optional[bool]) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "NO"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("gpu_campaign"))
    parser.add_argument("--json", type=pathlib.Path, default=pathlib.Path("counter_provenance_audit_v2.json"))
    parser.add_argument("--md", type=pathlib.Path, default=pathlib.Path("COUNTER_PROVENANCE_AUDIT_V2.md"))
    args = parser.parse_args(argv)

    root = args.root
    if not root.is_dir():
        parser.error(f"root directory not found: {root}")

    report = build_report(root)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    args.md.write_text(render_markdown(report))

    # Required per-arm print line.
    print("arm, envelopes, judged, late, duplicate, invalid, conserved, persisted_envelope_lines, persisted_verdict_lines")
    for arm in report["arms"]:
        print(
            "{arm}, {env}, {judged}, {late}, {dup}, {invalid}, {cons}, {pe}, {pv}".format(
                arm=arm["relative_dir"],
                env=arm["envelopes"],
                judged=arm["judged"],
                late=arm["late"],
                dup=arm["duplicate"],
                invalid=arm["invalid"],
                cons=str(arm["conserved"]).lower(),
                pe=arm["persisted_envelope_lines"],
                pv=arm["persisted_verdict_lines"],
            )
        )
    summary = report["summary"]
    print("")
    print(
        f"[summary] arms_with_dict_status={summary['n_arms_with_dict_collector_status']} "
        f"conserved={summary['n_conserved']}/{summary['n_conservation_evaluable']} "
        f"violations={summary['n_conservation_violations']} "
        f"periodic_provenance_match={summary['n_periodic_provenance_counters_match']} "
        f"periodic_provenance_mismatch={summary['n_periodic_provenance_counters_mismatch']} "
        f"periodic_all_match={summary['n_periodic_all_counters_match']}"
    )
    print(f"[wrote] {args.json}")
    print(f"[wrote] {args.md}")
    if not summary["all_conserved"]:
        print("CONSERVATION ASSERTION FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())