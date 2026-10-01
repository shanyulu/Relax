# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Replay the observer-only native-loss envelopes through pinned Relax code.

This evidence tool is read-only. It parses local artifacts, reports the saved
verdicts, then explicitly flushes the raw envelope tail to expose verdicts that
are absent from a non-terminal runtime snapshot. It never edits the inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple


PRODUCT_SHA = "927c5de2f5a8f307cad0c87f2c7eb2b78262334d"
ARMS = {
    "L-M1-on": "run_0c000000",
    "L-M2-on": "run_0d000000",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_object_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json_loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_object_pairs)


def read_json(path: Path) -> Dict[str, Any]:
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                value = strict_json_loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(value)
    return rows


def resolve_input(measurement_root: Path, relative_path: Path) -> Path:
    """Resolve an evidence input and reject paths/symlinks outside the root."""
    root = measurement_root.resolve(strict=True)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"unsafe evidence path: {relative_path}")
    resolved = (root / relative_path).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evidence path escapes measurement root: {relative_path}") from exc
    return resolved


def verify_job_log_hash(job_log: Path, expected_hash: Any) -> str:
    if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("manifest has missing or invalid job_log_sha256")
    actual_hash = sha256(job_log)
    if actual_hash != expected_hash:
        raise ValueError(f"job.log SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
    return actual_hash


def validate_envelope_identities(envelopes: List[Dict[str, Any]]) -> int:
    identities = set()
    for index, row in enumerate(envelopes, 1):
        rank = row.get("rank")
        seq = row.get("seq")
        stage = row.get("name")
        if type(rank) is not int or type(seq) is not int or not isinstance(stage, str) or not stage:
            raise ValueError(f"invalid envelope identity at row {index}")
        identity = (rank, seq, stage)
        if identity in identities:
            raise ValueError(f"duplicate envelope identity at row {index}: {identity}")
        identities.add(identity)
    return len(identities)


def signature(verdict: Dict[str, Any]) -> Tuple[str, str, int, int, str]:
    required = ("cohort", "name", "rank", "window_index", "kind")
    missing = [field for field in required if field not in verdict]
    if missing:
        raise ValueError(f"saved verdict identity missing fields: {', '.join(missing)}")
    cohort, name, rank, window_index, kind = (verdict[field] for field in required)
    if not isinstance(cohort, str) or not cohort:
        raise ValueError("saved verdict identity cohort must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise ValueError("saved verdict identity name must be a non-empty string")
    if type(rank) is not int or rank < 0:
        raise ValueError("saved verdict identity rank must be a non-negative integer")
    if type(window_index) is not int or window_index < 0:
        raise ValueError("saved verdict identity window_index must be a non-negative integer")
    if not isinstance(kind, str) or kind not in ("straggler", "recovered", "uncertain"):
        raise ValueError("saved verdict identity kind is invalid")
    return cohort, name, rank, window_index, kind


def validate_saved_verdicts(verdicts: List[Dict[str, Any]]) -> List[Tuple[str, str, int, int, str]]:
    signatures = []
    seen = set()
    for index, verdict in enumerate(verdicts, 1):
        identity = signature(verdict)
        if identity in seen:
            raise ValueError(f"duplicate saved verdict identity at row {index}: {identity}")
        seen.add(identity)
        signatures.append(identity)
    return signatures


def verify_profiler_job_log(job_log: Path) -> Dict[str, Any]:
    text = job_log.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    started_roles = set()
    enabled_windows: Dict[str, List[Any]] = {"sender": [], "collector": []}
    for line in text.splitlines():
        started = re.search(r"straggler profiler started:\s*role=(sender|collector)\b", line)
        if started:
            started_roles.add(started.group(1))
        enabled = re.search(r"straggler profiler enabled:\s*role=(sender|collector)\b", line)
        if enabled:
            window = re.search(r"\bwindow=([0-9]+(?:\.[0-9]+)?)s\b", line)
            enabled_windows[enabled.group(1)].append(window.group(1) if window else None)

    roles = ("sender", "collector")
    missing_started = [role for role in roles if role not in started_roles]
    if missing_started:
        raise ValueError(f"missing straggler profiler started roles in {job_log}: {missing_started}")
    for role in roles:
        windows = enabled_windows[role]
        if not windows:
            raise ValueError(f"missing straggler profiler enabled role={role} in {job_log}")
        if any(window != "5.0" for window in windows):
            raise ValueError(f"unexpected profiler window for role={role}: {windows}")
    return {
        "started_roles": sorted(started_roles),
        "enabled_roles": sorted(role for role in roles if enabled_windows[role]),
        "window_seconds_by_role": {role: enabled_windows[role] for role in roles},
    }


def event_summary(verdict: Dict[str, Any]) -> Dict[str, Any]:
    facts = verdict.get("facts") or {}
    host = verdict.get("rank_host_ms")
    host_reference = verdict.get("reference_host_ms")
    device = verdict.get("rank_device_ms")
    device_reference = verdict.get("reference_device_ms")
    return {
        "kind": verdict.get("kind"),
        "window": verdict.get("window_index"),
        "rank": verdict.get("rank"),
        "stage": verdict.get("name"),
        "reason": verdict.get("reason"),
        "consecutive_windows": verdict.get("consecutive_windows"),
        "host_ms": host,
        "reference_host_ms": host_reference,
        "host_ratio": (host / host_reference if host_reference else None),
        "device_ms": device,
        "reference_device_ms": device_reference,
        "device_ratio": (device / device_reference if device_reference else None),
        "samples_rank": facts.get("samples_rank"),
        "samples_peers": facts.get("samples_peers"),
        "coverage_ratio": facts.get("coverage_ratio"),
        "comparable_peers": facts.get("comparable_peers"),
        "comparable_coverage_ratio": facts.get("comparable_coverage_ratio"),
        "tokens_delta": facts.get("tokens_delta"),
        "sequences_delta": facts.get("sequences_delta"),
        "microbatches_delta": facts.get("microbatches_delta"),
        "workload_comparable": facts.get("workload_comparable"),
    }


def verify_no_injected_slowdown(job_log: Path) -> Dict[str, str]:
    text = job_log.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    required = {
        "error_injection_rate": "0",
        "fault_injector_delay_start_iteration": "None",
        "fault_injector_fault_delay": "None",
        "fault_injector_fault_probabilities": "None",
        "fault_injector_fault_types": "None",
        "fault_injector_ranks": "None",
        "fault_injector_num_ranks": "None",
    }
    observed: Dict[str, str] = {}
    for key in required:
        match = re.search(rf"^\s*{re.escape(key)}\s+\.*\s*(\S+)\s*$", text, re.MULTILINE)
        if match is None:
            raise ValueError(f"missing injection setting {key} in {job_log}")
        observed[key] = match.group(1)
    for key, expected in required.items():
        if observed[key] != expected:
            raise ValueError(f"unexpected injected-fault setting {key}={observed[key]} in {job_log}")
    return observed


def verify_product(product_root: Path) -> None:
    head = subprocess.run(
        ["git", "-C", str(product_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(product_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if head != PRODUCT_SHA:
        raise ValueError(f"product checkout is {head}; expected {PRODUCT_SHA}")
    if status.strip():
        raise ValueError("product checkout has uncommitted changes")


def replay_arm(
    arm: str,
    measurement_root: Path,
    StragglerConfig: Any,
    StragglerDetector: Any,
) -> Dict[str, Any]:
    run_id = ARMS[arm]
    run_dir = resolve_input(measurement_root, Path(arm) / "straggler" / run_id)
    manifest_path = resolve_input(measurement_root, Path(arm) / "manifest.json")
    job_log_path = resolve_input(measurement_root, Path(arm) / "job.log")
    manifest = read_json(manifest_path)
    if manifest.get("product_sha") != PRODUCT_SHA or manifest.get("arm") != arm:
        raise ValueError(f"manifest identity mismatch for {arm}")
    if manifest.get("status") != "SUCCEEDED" or manifest.get("valid") is not True:
        raise ValueError(f"arm is not successful and valid: {arm}")

    launch = manifest.get("launch_spec") or {}
    observer = launch.get("observer") or {}
    if observer.get("RELAX_STRAGGLER_ENABLE") != "1":
        raise ValueError(f"observer is not enabled in {arm}")

    run_relative = run_dir.relative_to(measurement_root.resolve(strict=True))
    envelopes_path = resolve_input(measurement_root, run_relative / "straggler_envelopes.jsonl")
    verdicts_path = resolve_input(measurement_root, run_relative / "straggler_verdicts.jsonl")
    envelopes = read_jsonl(envelopes_path)
    identity_count = validate_envelope_identities(envelopes)
    saved = read_jsonl(verdicts_path)
    saved_signatures = validate_saved_verdicts(saved)
    status = read_json(resolve_input(measurement_root, run_relative / "collector_status.json"))
    runtime = read_json(resolve_input(measurement_root, run_relative / "runtime_status.json"))
    verify_job_log_hash(job_log_path, manifest.get("job_log_sha256"))
    injection_config = verify_no_injected_slowdown(job_log_path)
    profiler_config = verify_profiler_job_log(job_log_path)

    config = StragglerConfig(
        enabled=True,
        window_seconds=float(observer.get("RELAX_STRAGGLER_WINDOW_S", 5)),
        warmup_windows=int(observer.get("RELAX_STRAGGLER_WARMUP_WINDOWS", 2)),
        work_tolerance=float(status["work_tolerance"]),
        min_stage_ms=float(status["min_stage_ms"]),
        persist_windows=int(status["persist_windows"]),
        min_cohort_size=2,
    )
    detector = StragglerDetector(config)
    for envelope in envelopes:
        detector.observe(SimpleNamespace(**envelope))
    detector.flush()
    replayed = [verdict.to_dict() for verdict in detector.drain_verdicts()]
    replayed_active = detector.active_stragglers()

    saved_confirmed = [row for row in saved if row.get("kind") == "straggler"]
    saved_recovered = [row for row in saved if row.get("kind") == "recovered"]
    saved_signature_set = set(saved_signatures)
    replay_only = [row for row in replayed if signature(row) not in saved_signature_set]
    replay_only_confirmed = [row for row in replay_only if row.get("kind") == "straggler"]

    sender_status = []
    for path in sorted(run_dir.glob("runtime_status_rank*.json")):
        safe_path = resolve_input(measurement_root, path.relative_to(measurement_root.resolve(strict=True)))
        rank_status = read_json(safe_path)
        sender = rank_status.get("sender")
        if sender:
            sender_status.append(
                {
                    "rank": (rank_status.get("identity") or {}).get("rank"),
                    "queued": sender.get("queued"),
                    "sent": sender.get("sent"),
                    "dropped_queue_full": sender.get("dropped_queue_full"),
                    "send_errors": sender.get("send_errors"),
                }
            )

    return {
        "arm": arm,
        "run_id": envelopes[0].get("run_id") if envelopes else None,
        "product_sha": manifest.get("product_sha"),
        "valid": manifest.get("valid"),
        "injection_config_from_job_log": injection_config,
        "profiler_config_from_job_log": profiler_config,
        "raw": {
            "envelope_lines": len(envelopes),
            "envelope_unique_rank_seq_stage": identity_count,
            "envelope_sha256": sha256(envelopes_path),
            "verdict_lines": len(saved),
            "verdict_sha256": sha256(verdicts_path),
            "saved_kinds": {
                kind: sum(row.get("kind") == kind for row in saved) for kind in ("straggler", "recovered", "uncertain")
            },
        },
        "saved_confirmed": [event_summary(row) for row in saved_confirmed],
        "saved_recoveries": [event_summary(row) for row in saved_recovered],
        "offline_replay_only_confirmed": [event_summary(row) for row in replay_only_confirmed],
        "offline_replay_active_at_end": replayed_active,
        "runtime_snapshot": {
            "closed": runtime.get("closed"),
            "pending_readouts": (runtime.get("observer") or {}).get("pending"),
            "observer_queue_drops": {
                key: (runtime.get("observer") or {}).get(key)
                for key in ("dropped_pending_full", "dropped_output_full")
            },
            "collector_open_windows": status.get("open_windows"),
            "collector_envelopes": status.get("envelopes"),
            "collector_judged": status.get("judged_packets"),
            "collector_flushed_lines": status.get("flushed_lines"),
            "recorded_drop_or_error_counters": {
                key: status.get(key)
                for key in (
                    "late_packets",
                    "duplicate_packets",
                    "invalid_packets",
                    "invalid_samples",
                    "invalid_device_samples",
                    "ingest_errors",
                    "observe_errors",
                    "sample_evictions",
                    "write_errors",
                    "pending_line_drops",
                    "close_errors",
                )
            },
            "sender_snapshots": sender_status,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", required=True, type=Path, help="clean checkout at the pinned product SHA")
    parser.add_argument(
        "--measurement-root", required=True, type=Path, help="directory containing L-M1-on and L-M2-on"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    product_root = args.product_root.resolve()
    verify_product(product_root)
    sys.path.insert(0, str(product_root))
    from relax.utils.straggler.config import StragglerConfig
    from relax.utils.straggler.detector import StragglerDetector

    result = {
        "schema": "native-loss-straggler-offline-replay-v1",
        "product_sha": PRODUCT_SHA,
        "raw_artifacts_are_local_only": True,
        "offline_replay_flushes_open_windows": True,
        "arms": [],
    }
    for arm in ARMS:
        result["arms"].append(replay_arm(arm, args.measurement_root, StragglerConfig, StragglerDetector))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
