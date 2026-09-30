#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Replay frozen parameter evidence using three explicit, confined root
mappings."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Callable

import c2_parameter_bounded_927c5de as bounded
import c2_parameter_campaign_927c5de as campaign
import c2_parameter_execution_lock_927c5de as execution
import c2_parameter_verdict_927c5de as frozen


OLD_REPO = Path("/tmp/codex-task11-evidence")
OLD_PRODUCT = Path("/root/autodl-tmp/relax-work/task11-c2-927c5de")
OLD_DATA = Path("/root/autodl-tmp/task11-3090")
BASE = Path("evidence/gpu_campaign/task11_3090/c2_parameter")
CAMPAIGN = Path("formal/parameter-measurement-4c74209")


def strict_json(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key}: {path}")
            result[key] = value
        return result

    payload = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


class Roots:
    """No mount changes, copied manifests, symlinks or global Path mutation."""

    def __init__(self, repo: Path, product: Path, data: Path):
        self.mapping = {
            old: new.resolve(strict=True) for old, new in zip((OLD_REPO, OLD_PRODUCT, OLD_DATA), (repo, product, data))
        }
        values = list(self.mapping.values())
        if any(not path.is_dir() for path in values):
            raise ValueError("all three roots must be directories")
        if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(values) for b in values[i + 1 :]):
            raise ValueError("root mappings must be distinct and non-overlapping")
        for logical, actual in self.mapping.items():
            if any(actual.is_relative_to(old) for old in self.mapping) and actual != logical:
                raise ValueError("actual root ambiguously overlaps the frozen logical namespace")

    def path(self, value: str | Path) -> Path:
        raw = Path(value)
        if not raw.is_absolute() or ".." in raw.parts:
            raise ValueError(f"unconfined absolute evidence path: {value}")
        for old, new in self.mapping.items():
            if raw.is_relative_to(old):
                target = new / raw.relative_to(old)
                resolved = target.resolve()
                if not resolved.is_relative_to(new):
                    raise ValueError(f"symlink escapes mapped root: {value}")
                return resolved
        for root in self.mapping.values():
            if raw.is_relative_to(root) and raw.resolve().is_relative_to(root):
                return raw.resolve()
        raise ValueError(f"path is outside the three frozen roots: {value}")

    def relative(self, parent: Path, value: Any, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise frozen.InvalidError(f"missing {label}")
        path = Path(value)
        if path.is_absolute():
            target = self.path(path)
            if not target.is_relative_to(parent.resolve()):
                raise frozen.InvalidError(f"absolute {label} escapes parent")
            return target
        if ".." in path.parts:
            raise frozen.InvalidError(f"parent traversal in {label}")
        target = self.path(parent / path)
        if not target.is_relative_to(parent.resolve()):
            raise frozen.InvalidError(f"relative {label} escapes parent")
        return target


def private_lineage(roots: Roots) -> dict[str, Any]:
    """Reuse frozen function bytecode with only local path construction mapped.

    The original module dictionaries and pathlib.Path are never mutated.
    Dynamic imports inside these functions retain the original hash/tree/native
    readers, and consume actual confined paths.
    """
    namespace = dict(vars(campaign))
    namespace["Path"] = roots.path
    for name in ("validate_arm", "validate_adapter_source", "validate_inventory_lineage", "_validate_execution"):
        original = getattr(campaign, name)
        namespace[name] = types.FunctionType(
            original.__code__, namespace, name, original.__defaults__, original.__closure__
        )
    return namespace


def private_comparison(roots: Roots) -> Callable:
    proxy = types.SimpleNamespace(**vars(frozen))
    proxy.resolve_relative = roots.relative
    namespace = dict(vars(bounded))
    namespace["frozen"] = proxy
    original = bounded.compare_pair
    return types.FunctionType(
        original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__
    )


def preflight(roots: Roots, *, metadata_only: bool) -> tuple[dict, Path, list[Path]]:
    repo = roots.mapping[OLD_REPO]
    if Path(__file__).resolve().parent != repo / "evidence/tools":
        raise ValueError("invoke the replay script from the mapped evidence repository")
    execution_path = repo / BASE / "locks/P_EXECUTION_LOCK.json"
    strict_json(execution_path)
    execution.verify(repo, execution_path)
    lock_path = repo / BASE / "locks/P_MEASUREMENT_LOCK.json"
    lock = strict_json(lock_path)
    campaign.validate_lock(lock)
    local = private_lineage(roots)
    local["_validate_execution"](
        argparse.Namespace(product=roots.mapping[OLD_PRODUCT]), lock, campaign.MEASUREMENT_ARMS
    )
    calibration_path = repo / BASE / "P_CALIBRATION_RESULT.json"
    strict_json(calibration_path)
    calibration, calibration_sha = frozen.read_calibration(calibration_path)
    if calibration_sha != lock["CALIBRATION_RESULT_SHA256"]:
        raise ValueError("measurement lock calibration binding mismatch")
    if calibration["tolerance_table_sha256"] != lock["TOLERANCE_TABLE_SHA256"]:
        raise ValueError("measurement lock tolerance table mismatch")
    if execution.committed_file(repo, calibration_path) != lock["CALIBRATION_RESULT_COMMIT"]:
        raise ValueError("calibration commit binding mismatch")
    lock_sha = bounded.sha256_file(lock_path)
    root = roots.mapping[OLD_DATA] / CAMPAIGN
    fingerprint = campaign._source_fingerprint(roots.mapping[OLD_PRODUCT])
    for name in campaign.MEASUREMENT_ARMS:
        strict_json(root / name / "manifest.json")
        manifest = local["validate_arm"](root / name, lock, lock_sha)
        if manifest["driver_source_sha256_before"] != fingerprint:
            raise ValueError(f"product source fingerprint mismatch: {name}")
    pairs = []
    for pair_id in ("P-M1", "P-M2"):
        pair_path = root / f"{pair_id}_PAIR_MANIFEST.json"
        pair = strict_json(pair_path)
        expected = {
            "pair_id": pair_id,
            "product_sha": lock["PRODUCT_SHA"],
            "protocol_sha256": lock["PROTOCOL_SHA256"],
            "calibration_sha256": calibration_sha,
            "measurement_lock_sha256": lock_sha,
        }
        if any(pair.get(key) != value for key, value in expected.items()):
            raise ValueError(f"pair binding mismatch: {pair_id}")
        for side in ("off", "on"):
            arm = root / f"{pair_id}-{side}"
            inventory_path = roots.relative(pair_path.parent, pair.get(f"{side}_inventory"), "inventory")
            if not inventory_path.is_relative_to(arm):
                raise ValueError("inventory is outside its frozen arm")
            if bounded.sha256_file(inventory_path) != pair.get(f"{side}_inventory_sha256"):
                raise ValueError("pair inventory hash mismatch")
            inventory = strict_json(inventory_path)
            bounded.Inventory(
                inventory_path,
                product_sha=lock["PRODUCT_SHA"],
                protocol_sha256=lock["PROTOCOL_SHA256"],
                arm_name=arm.name,
                measurement_lock_sha256=lock_sha,
            )
            identity = {"schema_version": 2}
            for field in ("recipe", "dataset", "env_fingerprint", "comparator"):
                identity[field + "_sha256"] = lock[field.upper() + "_SHA256"]
            if any(inventory.get(key) != value for key, value in identity.items()):
                raise ValueError("formal inventory identity mismatch")
            adapter_dir = roots.path(inventory["checkpoint_root"])
            if adapter_dir.parent != arm:
                raise ValueError("adapter directory outside frozen arm")
            record = strict_json(adapter_dir / "ADAPTER_RECORD.json")
            expected_record = {
                "schema": "C2_927C5DE_DCP_ADAPTER/v1",
                "arm_name": arm.name,
                "status": "REVIEWED_TRUSTED_CAMPAIGN_ONLY",
                "adapter_sha256": lock["ADAPTER_SHA256"],
            }
            if any(record.get(key) != value for key, value in expected_record.items()):
                raise ValueError("adapter identity/status/frozen source mismatch")
            expected_lineage = {
                "arm_manifest_sha256": bounded.sha256_file(arm / "manifest.json"),
                "adapter_record_sha256": bounded.sha256_file(adapter_dir / "ADAPTER_RECORD.json"),
                "source_tree_sha256": record.get("source_tree_sha256"),
                "sanitized_sha256": record.get("sanitized_sha256"),
            }
            if inventory.get("lineage") != expected_lineage:
                raise ValueError("formal inventory lineage record mismatch")
            if roots.path(record["source_checkpoint_root"]) != arm / "checkpoints":
                raise ValueError("adapter source checkpoint path mismatch")
            iteration = roots.path(record["source_iteration_dir"])
            raw = roots.path(record["raw_converted_path"])
            if not iteration.is_relative_to(arm / "checkpoints") or raw.parent != arm / f"{adapter_dir.name}_raw":
                raise ValueError("adapter lineage path escapes owned directories")
            from c2_parameter_dcp_adapter_927c5de import find_iteration

            if find_iteration(arm / "checkpoints").resolve() != iteration:
                raise ValueError("adapter iteration differs from retained checkpoint marker")
            for path in (iteration / ".metadata", raw, adapter_dir / "converted_tensors.pt"):
                if not path.is_file():
                    raise FileNotFoundError(path)
            for entry in inventory["tensors"]:
                payload = roots.relative(inventory_path.parent, entry.get("npy"), "tensor payload")
                if not payload.is_relative_to(arm) or not payload.is_file():
                    raise ValueError("tensor payload missing or outside frozen arm")
            if not metadata_only:
                local["validate_inventory_lineage"](inventory_path, arm, lock, lock_sha)
        pairs.append(pair_path)
    return calibration, calibration_path, pairs


def result(roots: Roots, calibration: dict, calibration_path: Path, pairs: list[Path]) -> dict:
    compare = private_comparison(roots)
    calibration_sha = bounded.sha256_file(calibration_path)
    results, violations = [], []
    for pair_path in pairs:
        pair, errors = compare(pair_path, calibration, calibration_sha)
        results.append(pair)
        violations.extend(f"{pair['pair_id']}: {item}" for item in errors)
    missing = [name for pair in results for name in pair["missing_tolerances"]]
    verdict = "NOT_PASS" if violations else ("INCOMPLETE" if missing else "PASS")
    reason = "; ".join(violations or ([f"missing tolerances: {', '.join(missing)}"] if missing else [])) or None
    payload = frozen.result_payload(verdict, reason, calibration=calibration_path, pairs=results)
    # Preserve the frozen logical identity rather than the recovery machine's location.
    payload["calibration_path"] = str(OLD_REPO / calibration_path.relative_to(roots.mapping[OLD_REPO]))
    payload["self_sha256"] = frozen.canonical_sha256(payload)
    return payload


def mapping_audit(roots: Roots, *, metadata_only: bool) -> dict:
    payload = {
        "schema": "C2_PARAMETER_REPLAY_MAPPING/v1",
        "mappings": {str(old): str(new) for old, new in roots.mapping.items()},
        "replay_source_sha256": bounded.sha256_file(Path(__file__)),
        "requested_validation_mode": "METADATA_ONLY" if metadata_only else "FULL_LINEAGE_AND_NUMERIC",
        "frozen_manifests_modified": False,
        "self_sha256": None,
    }
    payload["self_sha256"] = frozen.canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--metadata-only", action="store_true", help="path/source checks only; never an acceptance verdict"
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--audit-out", type=Path, help="separate root mapping receipt; never changes verdict fields")
    args = parser.parse_args()
    if not args.metadata_only and args.out is None:
        parser.error("full replay requires --out")
    if args.out is not None and args.audit_out is not None and args.out.resolve() == args.audit_out.resolve():
        parser.error("verdict and mapping receipt must use distinct paths")
    if any(path is not None and path.exists() for path in (args.out, args.audit_out)):
        parser.error("refusing to overwrite output")
    try:
        roots = Roots(args.repo_root, args.product_root, args.data_root)
        calibration, calibration_path, pairs = preflight(roots, metadata_only=args.metadata_only)
        if args.audit_out is not None:
            with args.audit_out.open("x") as target:
                target.write(
                    json.dumps(mapping_audit(roots, metadata_only=args.metadata_only), indent=2, sort_keys=True) + "\n"
                )
        if args.metadata_only:
            print(
                "METADATA_ONLY: source/commit/path checks complete; large-byte hashes and numeric verdict NOT VERIFIED"
            )
            return 0
        payload = result(roots, calibration, calibration_path, pairs)
        with args.out.open("x") as target:
            target.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"parameter replay verdict: {payload['verdict']}")
        return 0 if payload["verdict"] == "PASS" else 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
        frozen.InvalidError,
        frozen.IncompleteError,
    ) as exc:
        print(f"REPLAY REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
