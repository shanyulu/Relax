#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""C2 native extraction from campaign job.logs (read-only, safe during flight).

Extracts per arm:
  - update_count        : number of unique `perf N:` step records
  - token_series        : per-step actor_train_tokens (data-order parity)
  - train_time_series   : per-step perf/train_time
  - nan_inf_findings    : bare nan/inf tokens in NUMERIC context only
                          (word-embedded hits like `infinite retries`,
                          `check_for_nan_in_loss_and_grad`, `provenance` are excluded)

Writes <campaign_root>/c2_native_extraction.json and prints a per-session
OFF-vs-ON parity table. Native `step N:` records also contain loss, gradient
norm and learning rates in this campaign. Missing, duplicate or malformed
records invalidate the extraction; this is not a checkpoint-equivalence test.
"""

import ast
import json
import math
import re
import sys
from pathlib import Path


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PERF_RE = re.compile(r"perf (\d+): (\{.*\})\s*$")
NATIVE_RE = re.compile(r"\bstep (\d+): (\{.*\})\s*$")
# bare nan/inf not embedded in an identifier word (numeric context only)
NAN_RE = re.compile(r"(?<![A-Za-z_0-9])(?:[Nn]a[Nn]|[Ii]nf)(?![A-Za-z_0-9])")


def strip_ansi(line: str) -> str:
    return ANSI_RE.sub("", line)


def parse_arm(arm_dir: Path, expected_steps: int | None = None) -> dict:
    log = arm_dir / "job.log"
    if not log.exists():
        return {"arm": arm_dir.name, "log_present": False}
    steps = {}
    native = {}
    errors = []
    nan_findings = []
    with log.open("r", errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = strip_ansi(raw)
            m = PERF_RE.search(line)
            native_match = NATIVE_RE.search(line)
            if native_match:
                try:
                    payload = ast.literal_eval(native_match.group(2))
                    index = int(native_match.group(1))
                    if not isinstance(payload, dict) or payload.get("train/step") != index:
                        raise ValueError("native step ordinal mismatch")
                    if index in native:
                        raise ValueError("duplicate native step")
                    for key in ("train/loss", "train/grad_norm"):
                        value = payload.get(key)
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                            raise ValueError(f"missing or nonfinite {key}")
                    rates = {key: value for key, value in payload.items() if key.startswith("train/lr-")}
                    if not rates or any(
                        not isinstance(value, (int, float)) or not math.isfinite(value) for value in rates.values()
                    ):
                        raise ValueError("missing or nonfinite learning rate")
                    native[index] = payload
                except (ValueError, SyntaxError) as exc:
                    errors.append({"line": lineno, "kind": "native-record", "error": str(exc)})
            if m:
                try:
                    payload = ast.literal_eval(m.group(2))
                    if isinstance(payload, dict):
                        index = int(m.group(1))
                        if index in steps:
                            errors.append({"line": lineno, "kind": "duplicate-perf-step"})
                        else:
                            steps[index] = payload
                except (ValueError, SyntaxError):
                    nan_findings.append({"line": lineno, "kind": "unparsable-perf-dict"})
                continue
            if NAN_RE.search(line):
                nan_findings.append({"line": lineno, "text": line.strip()[:240]})
    ids = sorted(steps)
    native_ids = sorted(native)
    complete = bool(ids) and ids == native_ids == list(range(len(ids)))
    if expected_steps is not None:
        complete = complete and len(ids) == expected_steps
    if not complete:
        errors.append({"kind": "missing-or-noncontiguous-steps"})
    if any(
        not isinstance(steps[i].get(key), (int, float)) or not math.isfinite(steps[i][key])
        for i in ids
        for key in ("perf/actor_train_tokens", "perf/train_time")
    ):
        errors.append({"kind": "missing-or-nonfinite-perf-fields"})
    return {
        "arm": arm_dir.name,
        "log_present": True,
        "update_count": len(ids),
        "step_ids_contiguous": ids == list(range(len(ids))),
        "token_series": [steps[i].get("perf/actor_train_tokens") for i in ids],
        "train_time_series": [steps[i].get("perf/train_time") for i in ids],
        "nan_inf_findings": nan_findings,
        "native_step_ids": native_ids,
        "loss_series": [native[i]["train/loss"] for i in native_ids],
        "grad_norm_series": [native[i]["train/grad_norm"] for i in native_ids],
        "learning_rate_series": [
            {key: value for key, value in native[i].items() if key.startswith("train/lr-")} for i in native_ids
        ],
        "extraction_errors": errors,
        "native_valid": complete and not errors and not nan_findings,
    }


def main() -> int:
    root = Path(sys.argv[1])
    arms = sorted(p for p in root.iterdir() if p.is_dir() and (p / "job.log").exists())
    result = {"campaign_root": str(root), "arms": {}}
    for arm_dir in arms:
        result["arms"][arm_dir.name] = parse_arm(arm_dir)

    sessions = {}
    for name, arm in result["arms"].items():
        if not arm.get("log_present"):
            continue
        session = name.rsplit("-", 1)[0]
        sessions.setdefault(session, {})[name.rsplit("-", 1)[1]] = arm
    parity = {}
    for session in sorted(sessions):
        s = sessions[session]
        if "off" not in s or "on" not in s:
            parity[session] = {"status": "incomplete", "arms": sorted(s)}
            continue
        parity[session] = {
            "status": "complete",
            "update_count_off_on": [s["off"]["update_count"], s["on"]["update_count"]],
            "updates_equal": s["off"]["update_count"] == s["on"]["update_count"],
            "token_series_equal": s["off"]["token_series"] == s["on"]["token_series"],
            "nan_inf_off_on": [
                len(s["off"]["nan_inf_findings"]),
                len(s["on"]["nan_inf_findings"]),
            ],
        }
    result["session_parity"] = parity

    out = root / "c2_native_extraction.json"
    out.write_text(json.dumps(result, indent=1))
    print(f"wrote {out}")
    for session, p in parity.items():
        print(session, json.dumps(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
