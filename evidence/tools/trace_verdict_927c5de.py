#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Freeze and evaluate the independent C2 overlap campaign for ``927c5de``.

The previous four-arm checker is intentionally not reused as a campaign
layout: this tool accepts arm descriptors from a frozen JSON configuration.
It first freezes an OFF/OFF envelope from exactly four OFF arms and two named
contrasts.  A later measurement configuration must reference the byte hash of
that immutable calibration result and supplies exactly two ON/OFF pairs, one
AB and one BA.

Raw trace files are verified against the configuration's complete SHA-256
ledger before metrics are computed.  ``cudaDeviceSynchronize`` is reported as
context only: it counts that API call, not all synchronization, and does not
enter the overlap verdict.

Exit status: PASS=0; NOT_PASS=1; INCOMPLETE=1; INVALID=2.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from trace_overlap_metrics import aggregate


SCHEMA = "task11-c2-overlap-927c5de-v1"
EXIT_CODES = {"PASS": 0, "NOT_PASS": 1, "INCOMPLETE": 1, "INVALID": 2}
EXPECTED_RANKS = [0, 1, 2, 3]


class IncompleteError(ValueError):
    """The pre-registered run did not retain all required trace inputs."""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Dict[str, Any]) -> str:
    """Hash structured results independent of indentation and field order."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def validated_result(path: Path) -> Dict[str, Any]:
    result = read_json(path)
    recorded = result.get("self_sha256")
    unsigned = {key: value for key, value in result.items() if key != "self_sha256"}
    if not isinstance(recorded, str) or recorded != canonical_sha256(unsigned):
        raise ValueError("calibration result self hash mismatch")
    return result


def write_once(path: Path, payload: Dict[str, Any]) -> None:
    """Publish a self-hashed result exactly once; never replace experiment
    output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = dict(payload)
    unsigned.pop("self_sha256", None)
    payload = {**unsigned, "self_sha256": canonical_sha256(unsigned)}
    try:
        with path.open("x") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite existing result: {path}") from exc


def fail(out: Path, verdict: str, reason: str) -> int:
    try:
        write_once(out, {"schema": SCHEMA, "verdict": verdict, "reason": reason})
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
    print(json.dumps({"verdict": verdict, "reason": reason}), file=sys.stderr)
    return EXIT_CODES[verdict]


def require_schema(config: Dict[str, Any], phase: str) -> None:
    if config.get("schema") != SCHEMA or config.get("phase") != phase:
        raise ValueError(f"expected {SCHEMA} {phase} configuration")
    if config.get("expected_ranks") != EXPECTED_RANKS:
        raise ValueError("protocol requires the unique DP4 ranks [0, 1, 2, 3]")
    if not isinstance(config.get("product_sha"), str) or len(config["product_sha"]) != 40:
        raise ValueError("missing or invalid product_sha")


def arm_map(config: Dict[str, Any], expected_count: int) -> Dict[str, Dict[str, Any]]:
    arms = config.get("arms")
    if not isinstance(arms, list) or len(arms) != expected_count:
        raise ValueError(f"configuration requires exactly {expected_count} arms")
    result = {}
    for arm in arms:
        if not isinstance(arm, dict):
            raise ValueError("arm descriptor must be an object")
        arm_id, path, condition = arm.get("id"), arm.get("path"), arm.get("condition")
        if not isinstance(arm_id, str) or not arm_id or not isinstance(path, str) or not path:
            raise ValueError("each arm needs a non-empty id and path")
        if condition not in {"OFF", "ON"}:
            raise ValueError(f"{arm_id}: condition must be OFF or ON")
        if arm_id in result:
            raise ValueError(f"duplicate arm id: {arm_id}")
        result[arm_id] = arm
    return result


def validate_calibration(config: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    require_schema(config, "calibration")
    arms = arm_map(config, 4)
    if any(arm["condition"] != "OFF" for arm in arms.values()):
        raise ValueError("all four calibration arms must be OFF")
    contrasts = config.get("contrasts")
    if not isinstance(contrasts, list) or len(contrasts) != 2:
        raise ValueError("calibration requires exactly two named OFF/OFF contrasts")
    seen_names, seen_arms = set(), set()
    for contrast in contrasts:
        if not isinstance(contrast, dict):
            raise ValueError("contrast must be an object")
        name, left, right = contrast.get("name"), contrast.get("left"), contrast.get("right")
        if not all(isinstance(item, str) and item for item in (name, left, right)):
            raise ValueError("contrast needs non-empty name, left, and right")
        if name in seen_names or left == right or left not in arms or right not in arms:
            raise ValueError("invalid or duplicate calibration contrast")
        seen_names.add(name)
        seen_arms.update((left, right))
    if seen_arms != set(arms):
        raise ValueError("each of the four calibration arms must occur in one named contrast")
    return arms, contrasts


def validate_measurement(config: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    require_schema(config, "measurement")
    arms = arm_map(config, 4)
    pairs = config.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 2:
        raise ValueError("measurement requires exactly two ON/OFF pairs")
    orders, seen_names, seen_arms = set(), set(), set()
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("pair must be an object")
        name, off, on, order = pair.get("name"), pair.get("off"), pair.get("on"), pair.get("order")
        if not all(isinstance(item, str) and item for item in (name, off, on, order)):
            raise ValueError("pair needs non-empty name, off, on, and order")
        if name in seen_names or order not in {"AB", "BA"} or off == on or off not in arms or on not in arms:
            raise ValueError("invalid or duplicate measurement pair")
        if arms[off]["condition"] != "OFF" or arms[on]["condition"] != "ON":
            raise ValueError("measurement pair must reference its declared OFF and ON arms")
        seen_names.add(name)
        orders.add(order)
        seen_arms.update((off, on))
    if orders != {"AB", "BA"} or seen_arms != set(arms):
        raise ValueError("measurement must use all arms in one AB and one BA pair")
    return arms, pairs


def trace_paths(raw_root: Path, arm: Dict[str, Any]) -> List[Path]:
    arm_path = raw_root / arm["path"]
    if not arm_path.is_dir():
        raise IncompleteError(f"{arm['id']}: missing arm directory")
    paths = sorted(arm_path.rglob("*.pt.trace.json.gz"))
    if not paths:
        raise IncompleteError(f"{arm['id']}: missing raw traces")
    return paths


def load_metrics(raw_root: Path, arms: Dict[str, Dict[str, Any]], ledger: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(ledger, dict) or not ledger:
        raise ValueError("raw_trace_hashes must be a non-empty object")
    discovered: Dict[str, Path] = {}
    for arm_id, arm in arms.items():
        for path in trace_paths(raw_root, arm):
            relative = path.relative_to(raw_root).as_posix()
            if relative in discovered:
                raise ValueError(f"duplicate raw trace path: {relative}")
            discovered[relative] = path
    if set(discovered) != set(ledger):
        missing = sorted(set(discovered) - set(ledger))
        extra = sorted(set(ledger) - set(discovered))
        raise ValueError(f"raw trace ledger drift: missing={missing}, extra={extra}")
    for relative, path in discovered.items():
        expected = ledger[relative]
        if not isinstance(expected, str) or len(expected) != 64 or file_sha256(path) != expected:
            raise ValueError(f"raw trace hash mismatch: {relative}")

    metrics = {}
    for arm_id, arm in arms.items():
        result = aggregate(trace_paths(raw_root, arm))
        if result["rank_ids"] != EXPECTED_RANKS or result["ranks_profiled"] != 4:
            raise ValueError(f"{arm_id}: duplicate, missing, or invalid DP4 rank coverage")
        ratio = result["overlap_ratio_total"]
        if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError(f"{arm_id}: invalid overlap ratio")
        metrics[arm_id] = result
    return metrics


def summary(metrics: Dict[str, Dict[str, Any]], arm_id: str) -> Dict[str, Any]:
    row = metrics[arm_id]
    return {
        "overlap_ratio": row["overlap_ratio_total"],
        "rank_ids": row["rank_ids"],
        "global_sync_count": row["global_sync_count_total"],
        "global_sync_scope": "cudaDeviceSynchronize API calls only; not all synchronization",
    }


def freeze(config_path: Path, raw_root: Path, out: Path) -> int:
    try:
        config = read_json(config_path)
        arms, contrasts = validate_calibration(config)
        metrics = load_metrics(raw_root, arms, config.get("raw_trace_hashes"))
        contrast_rows = []
        for contrast in contrasts:
            left, right = contrast["left"], contrast["right"]
            contrast_rows.append(
                {
                    **contrast,
                    "overlap_delta": abs(metrics[left]["overlap_ratio_total"] - metrics[right]["overlap_ratio_total"]),
                    "global_sync_delta": abs(
                        metrics[left]["global_sync_count_total"] - metrics[right]["global_sync_count_total"]
                    ),
                }
            )
        delta = 2.0 * max(row["overlap_delta"] for row in contrast_rows)
        payload = {
            "schema": SCHEMA,
            "kind": "calibration_result",
            "verdict": "PASS",
            "product_sha": config["product_sha"],
            "expected_ranks": EXPECTED_RANKS,
            "calibration_config_sha256": file_sha256(config_path),
            "raw_trace_hashes_sha256": canonical_sha256(config["raw_trace_hashes"]),
            "contrasts": contrast_rows,
            "delta_frozen": delta,
            "arms": {arm_id: summary(metrics, arm_id) for arm_id in arms},
        }
        write_once(out, payload)
    except IncompleteError as exc:
        return fail(out, "INCOMPLETE", str(exc))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return fail(out, "INVALID", str(exc))
    print(json.dumps({"verdict": "PASS", "delta_frozen": delta}, indent=2))
    return 0


def compare(config_path: Path, calibration_path: Path, raw_root: Path, out: Path) -> int:
    try:
        config = read_json(config_path)
        arms, pairs = validate_measurement(config)
        calibration = validated_result(calibration_path)
        if calibration.get("kind") != "calibration_result" or calibration.get("verdict") != "PASS":
            raise ValueError("measurement requires a passing calibration result")
        if config.get("calibration_result_sha256") != file_sha256(calibration_path):
            raise ValueError("measurement calibration_result_sha256 does not pin the supplied calibration")
        if (
            calibration.get("product_sha") != config["product_sha"]
            or calibration.get("expected_ranks") != EXPECTED_RANKS
        ):
            raise ValueError("measurement drift from frozen calibration product or rank set")
        delta = calibration.get("delta_frozen")
        if not isinstance(delta, (int, float)) or not math.isfinite(delta) or delta < 0:
            raise ValueError("invalid frozen calibration envelope")
        metrics = load_metrics(raw_root, arms, config.get("raw_trace_hashes"))
        rows = []
        for pair in pairs:
            off, on = pair["off"], pair["on"]
            off_ratio = metrics[off]["overlap_ratio_total"]
            on_ratio = metrics[on]["overlap_ratio_total"]
            rows.append(
                {
                    **pair,
                    "off_overlap_ratio": off_ratio,
                    "on_overlap_ratio": on_ratio,
                    "lower_bound": off_ratio - delta,
                    "overlap_delta_on_minus_off": on_ratio - off_ratio,
                    "pass": on_ratio >= off_ratio - delta,
                    "off_global_sync_count": metrics[off]["global_sync_count_total"],
                    "on_global_sync_count": metrics[on]["global_sync_count_total"],
                    "global_sync_scope": "cudaDeviceSynchronize API calls only; not all synchronization",
                }
            )
        verdict = "PASS" if all(row["pass"] for row in rows) else "NOT_PASS"
        payload = {
            "schema": SCHEMA,
            "kind": "measurement_result",
            "verdict": verdict,
            "product_sha": config["product_sha"],
            "expected_ranks": EXPECTED_RANKS,
            "measurement_config_sha256": file_sha256(config_path),
            "calibration_result_sha256": file_sha256(calibration_path),
            "delta_frozen": delta,
            "pairs": rows,
            "arms": {arm_id: summary(metrics, arm_id) for arm_id in arms},
        }
        write_once(out, payload)
    except IncompleteError as exc:
        return fail(out, "INCOMPLETE", str(exc))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return fail(out, "INVALID", str(exc))
    print(json.dumps({"verdict": verdict, "delta_frozen": delta, "pairs": rows}, indent=2))
    return EXIT_CODES[verdict]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze_parser = commands.add_parser("freeze", help="freeze a four-arm OFF/OFF calibration")
    compare_parser = commands.add_parser("compare", help="compare two preregistered ON/OFF pairs")
    for command in (freeze_parser, compare_parser):
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--raw-root", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
    compare_parser.add_argument("--calibration-result", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        return freeze(args.config, args.raw_root, args.out)
    return compare(args.config, args.calibration_result, args.raw_root, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
