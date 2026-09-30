#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Require committed measurement controls and immutable execution helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from c2_parameter_bounded_927c5de import sha256_file
from c2_parameter_campaign_927c5de import load_lock
from c2_parameter_verdict_927c5de import canonical_sha256


def committed_file(repo: Path, path: Path) -> str:
    relative = path.resolve().relative_to(repo.resolve())
    if subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain", "--", str(relative)], text=True
    ).strip():
        raise ValueError(f"uncommitted execution input: {relative}")
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "log", "-1", "--format=%H", "--", str(relative)], text=True
    ).strip()
    if len(commit) != 40:
        raise ValueError(f"execution input is not committed: {relative}")
    blob = subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{relative}"])
    if hashlib.sha256(blob).hexdigest() != sha256_file(path):
        raise ValueError(f"execution input differs from committed blob: {relative}")
    return commit


def create(repo: Path, measurement: Path, calibration: Path, sources: list[Path], out: Path) -> dict:
    lock = load_lock(measurement)
    if lock["STAGE"] != "MEASUREMENT" or lock["CALIBRATION_RESULT_SHA256"] != sha256_file(calibration):
        raise ValueError("measurement/calibration binding mismatch")
    paths = [measurement, calibration, *sources]
    records = {}
    for path in paths:
        relative = str(path.resolve().relative_to(repo.resolve()))
        if relative in records:
            raise ValueError("duplicate execution source")
        records[relative] = {"sha256": sha256_file(path), "commit": committed_file(repo, path)}
    payload = {
        "schema": "C2_PARAMETER_EXECUTION_LOCK/v1",
        "product_sha": lock["PRODUCT_SHA"],
        "measurement_lock": str(measurement.resolve().relative_to(repo.resolve())),
        "calibration_result": str(calibration.resolve().relative_to(repo.resolve())),
        "sources": records,
        "arm_order": lock["ARM_ORDER"],
        "expected_steps": lock["EXPECTED_STEPS"],
        "postprocessing": "AFTER_ALL_GPU_ARMS; SERIAL; NO_CONCURRENT_CACHE_EVICTION",
        "minimum_free_disk_gib": 40,
        "self_sha256": None,
    }
    payload["self_sha256"] = canonical_sha256(payload)
    with out.open("x") as target:
        target.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def verify(repo: Path, path: Path) -> dict:
    committed_file(repo, path)
    payload = json.loads(path.read_text())
    if payload.get("schema") != "C2_PARAMETER_EXECUTION_LOCK/v1" or payload.get("self_sha256") != canonical_sha256(
        payload
    ):
        raise ValueError("execution lock schema/self hash mismatch")
    for relative, record in payload["sources"].items():
        source = (repo / relative).resolve()
        if not source.is_relative_to(repo.resolve()) or sha256_file(source) != record["sha256"]:
            raise ValueError(f"execution source drift: {relative}")
        if committed_file(repo, source) != record["commit"]:
            raise ValueError(f"execution source commit drift: {relative}")
    lock = load_lock(repo / payload["measurement_lock"])
    if payload["product_sha"] != lock["PRODUCT_SHA"] or payload["arm_order"] != lock["ARM_ORDER"]:
        raise ValueError("execution/measurement identity mismatch")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--measurement", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--source", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "create":
        if args.measurement is None or args.calibration is None or not args.source:
            parser.error("create requires measurement, calibration and sources")
        create(args.repo, args.measurement, args.calibration, args.source, args.lock)
    else:
        verify(args.repo, args.lock)


if __name__ == "__main__":
    main()
