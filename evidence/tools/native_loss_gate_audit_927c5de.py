#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Independent, read-only integrity audit for the locked Task 11 loss campaign.

The frozen campaign runner, locks, tolerances, and verdict are inputs only.
This audit checks their lineage and recomputes the existing eight-arm result.
It does not launch jobs or write beneath the raw campaign directory.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
import native_loss_campaign_927c5de as frozen  # noqa: E402


PRODUCT_SHA = frozen.PRODUCT_SHA
CALIBRATION_ARMS = tuple(frozen.CALIBRATION_ARMS)
MEASUREMENT_ARMS = tuple(frozen.MEASUREMENT_ARMS)
EXPECTED_PAIRS = (("L-M1-off", "L-M1-on"), ("L-M2-off", "L-M2-on"))
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
BASE_HASH_FIELDS = (
    "recipe_sha256",
    "dataset_sha256",
    "environment_fingerprint_sha256",
    "protocol_sha256",
    "runner_sha256",
    "extractor_sha256",
    "straggler_source_sha256",
    "dashboard_gcs_sha256",
    "host_environment_sha256",
    "training_paths_sha256",
)
RUNTIME_HASH_FIELDS = (
    "model_tree_sha256",
    "model_config_sha256",
    "training_pip_freeze_sha256",
    "megatron_python_tree_sha256",
    "bridge_python_tree_sha256",
)
ACTIVATION_RE = re.compile(r"straggler profiler (?:started|enabled): role=(sender|collector)")


class AuditFailure(ValueError):
    """An evidence failure with a machine-readable outcome class."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        if status not in {"INVALID", "INCOMPLETE"}:
            raise ValueError(f"unsupported audit failure status: {status}")
        self.status = status


class DuplicateJSONKey(ValueError):
    """Raised when an object repeats a member name."""


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJSONKey(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha(value: dict[str, Any]) -> str:
    payload = {**value, "_self_sha256": None}
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise AuditFailure("INCOMPLETE", f"missing {label}: {path}")
    try:
        result = json.loads(path.read_text(), object_pairs_hook=reject_duplicate_json_keys)
    except (OSError, json.JSONDecodeError, DuplicateJSONKey) as exc:
        raise AuditFailure("INVALID", f"cannot read {label}: {exc}") from exc
    if not isinstance(result, dict):
        raise AuditFailure("INVALID", f"{label} must be a JSON object")
    return result


def secure_campaign_path(raw_root: Path, path: Path, label: str) -> Path:
    try:
        root = raw_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise AuditFailure("INCOMPLETE", f"missing raw campaign input {label}: {path}") from exc
    except (OSError, RuntimeError) as exc:
        raise AuditFailure("INVALID", f"cannot resolve raw campaign input {label}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AuditFailure("INVALID", f"raw campaign input escapes --raw-root through a symlink: {label}") from exc
    return resolved


def write_report_once(path: Path, report: str, raw_root: Path) -> None:
    root = raw_root.resolve(strict=True)
    parent = path.parent.resolve(strict=False)
    try:
        parent.relative_to(root)
    except ValueError:
        pass
    else:
        raise AuditFailure("INVALID", "report output must be outside the read-only raw campaign root")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(report)
    except FileExistsError as exc:
        raise AuditFailure("INVALID", f"refusing to overwrite existing report: {path}") from exc


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AuditFailure("INVALID", f"missing, empty, or malformed SHA-256: {label}")
    return value


def check_self_hash(value: dict[str, Any], label: str) -> None:
    expected = require_sha(value.get("_self_sha256"), f"{label}._self_sha256")
    if canonical_sha(value) != expected:
        raise AuditFailure("INVALID", f"{label} self-hash mismatch")


def validate_lock(lock: dict[str, Any], stage: str) -> None:
    check_self_hash(lock, f"{stage.lower()} lock")
    if lock.get("schema") != "TASK11_NATIVE_LOSS_CAMPAIGN/v1":
        raise AuditFailure("INVALID", f"{stage} lock schema mismatch")
    if lock.get("stage") != stage or lock.get("product_sha") != PRODUCT_SHA:
        raise AuditFailure("INVALID", f"{stage} lock stage/product mismatch")
    for field in BASE_HASH_FIELDS:
        require_sha(lock.get(field), f"{stage}.{field}")
    runtime = lock.get("runtime")
    if not isinstance(runtime, dict):
        raise AuditFailure("INVALID", f"{stage}.runtime is missing")
    for field in RUNTIME_HASH_FIELDS:
        require_sha(runtime.get(field), f"{stage}.runtime.{field}")
    expected_order = CALIBRATION_ARMS if stage == "CALIBRATION" else MEASUREMENT_ARMS
    if lock.get("arm_order") != list(expected_order):
        raise AuditFailure("INVALID", f"{stage} arm order must exactly match the frozen four-arm order")
    if len(lock["arm_order"]) != len(set(lock["arm_order"])):
        raise AuditFailure("INVALID", f"{stage} arm order contains duplicate IDs")
    if lock.get("steps") != frozen.STEPS or lock.get("seed") != frozen.SEED or lock.get("save") != 0:
        raise AuditFailure("INVALID", f"{stage} lock step/seed/SAVE contract mismatch")
    if lock.get("on_profile") != frozen.ON_PROFILE:
        raise AuditFailure("INVALID", f"{stage} ON profile mismatch")
    if stage == "MEASUREMENT":
        require_sha(lock.get("measurement_runner_sha256"), "MEASUREMENT.measurement_runner_sha256")
        require_sha(lock.get("calibration_lock_sha256"), "MEASUREMENT.calibration_lock_sha256")
        require_sha(lock.get("calibration_result_sha256"), "MEASUREMENT.calibration_result_sha256")
        commit = lock.get("calibration_result_commit")
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            raise AuditFailure("INVALID", "measurement calibration-result commit is absent or malformed")
        pairs = lock.get("measurement_pairs")
        if pairs != [list(pair) for pair in EXPECTED_PAIRS]:
            raise AuditFailure("INVALID", "measurement pairs must be exactly M1 off/on then M2 off/on")


def validate_calibration_result(
    result: dict[str, Any], calibration_lock: dict[str, Any], measurement_lock: dict[str, Any]
) -> dict[str, float]:
    check_self_hash(result, "calibration result")
    if (
        result.get("schema") != "TASK11_NATIVE_LOSS_CALIBRATION_RESULT/v1"
        or result.get("product_sha") != PRODUCT_SHA
        or result.get("lock_sha256") != calibration_lock.get("_self_sha256")
        or measurement_lock.get("calibration_lock_sha256") != calibration_lock.get("_self_sha256")
    ):
        raise AuditFailure("INVALID", "calibration result lineage does not match both locks")
    names = result.get("arm_manifests")
    if not isinstance(names, dict) or list(names) != list(CALIBRATION_ARMS):
        raise AuditFailure("INVALID", "calibration manifest inventory/order mismatch")
    for name, value in names.items():
        require_sha(value, f"calibration arm manifest hash {name}")
    raw_argv = result.get("raw_argv_sha256")
    if not isinstance(raw_argv, dict) or list(raw_argv) != list(CALIBRATION_ARMS):
        raise AuditFailure("INVALID", "calibration raw argv inventory/order mismatch")
    for name, value in raw_argv.items():
        require_sha(value, f"calibration raw argv hash {name}")
    require_sha(result.get("normalized_argv_sha256"), "calibration normalized argv hash")
    contrasts = result.get("contrasts")
    expected_contrasts = [list(pair) for pair in itertools.combinations(CALIBRATION_ARMS, 2)]
    if (
        not isinstance(contrasts, list)
        or [row.get("pair") for row in contrasts if isinstance(row, dict)] != expected_contrasts
    ):
        raise AuditFailure("INVALID", "calibration must contain the six unique OFF pairwise contrasts")
    tolerances = result.get("tolerances")
    if not isinstance(tolerances, dict) or set(tolerances) != {"loss_series", "grad_norm_series"}:
        raise AuditFailure("INVALID", "calibration tolerance fields are incomplete or unexpected")
    checked: dict[str, float] = {}
    for field in ("loss_series", "grad_norm_series"):
        maxima = []
        for index, row in enumerate(contrasts):
            try:
                measurement = row[field]
                maximum, step = measurement["max_abs_delta"], measurement["step"]
            except (KeyError, TypeError) as exc:
                raise AuditFailure("INVALID", f"calibration contrast {index}/{field} is incomplete") from exc
            if (
                isinstance(maximum, bool)
                or not isinstance(maximum, (int, float))
                or not math.isfinite(maximum)
                or maximum < 0
                or isinstance(step, bool)
                or not isinstance(step, int)
                or not 0 <= step < frozen.STEPS
            ):
                raise AuditFailure("INVALID", f"calibration contrast {index}/{field} is malformed")
            maxima.append(float(maximum))
        tolerance = tolerances[field]
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
            or float(tolerance) != 2.0 * max(maxima)
        ):
            raise AuditFailure("INVALID", f"calibration {field} tolerance does not match the frozen 2×max rule")
        checked[field] = float(tolerance)
    return checked


def validate_result_commit(repo: Path, commit: str, relpath: Path, expected_sha: str) -> None:
    try:
        payload = subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{relpath.as_posix()}"])
    except subprocess.CalledProcessError as exc:
        raise AuditFailure("INVALID", "calibration-result commit does not contain the locked result") from exc
    if sha256_bytes(payload) != expected_sha:
        raise AuditFailure("INVALID", "calibration-result commit content differs from the measurement lock")


def normalize_argv(payload: bytes) -> tuple[list[str], str]:
    try:
        argv = frozen.validate_resolved_argv(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuditFailure("INVALID", f"resolved training argv is invalid: {exc}") from exc
    normalized = frozen.normalized_argv_sha256(argv)
    return argv, normalized


def validate_numeric_series(parsed: dict[str, Any], name: str) -> None:
    if parsed.get("arm") != name or parsed.get("native_valid") is not True:
        raise AuditFailure("INVALID", f"{name}: native extraction did not validate")
    if parsed.get("extraction_errors"):
        raise AuditFailure("INVALID", f"{name}: duplicate, malformed, or missing step records")
    if parsed.get("nan_inf_findings"):
        raise AuditFailure("INVALID", f"{name}: log contains NaN/Inf findings")
    ids = parsed.get("native_step_ids")
    if not isinstance(ids, list) or ids != list(range(frozen.STEPS)) or len(set(ids)) != frozen.STEPS:
        raise AuditFailure("INVALID", f"{name}: step IDs are missing, duplicated, or out of sequence")
    if parsed.get("update_count") != frozen.STEPS or parsed.get("step_ids_contiguous") is not True:
        raise AuditFailure("INVALID", f"{name}: expected exactly 48 contiguous updates")
    for field in ("loss_series", "grad_norm_series", "token_series", "train_time_series"):
        values = parsed.get(field)
        if not isinstance(values, list) or len(values) != frozen.STEPS:
            raise AuditFailure("INVALID", f"{name}: {field} must have 48 entries")
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise AuditFailure("INVALID", f"{name}: {field} contains a nonnumeric or nonfinite value")
    rates = parsed.get("learning_rate_series")
    if not isinstance(rates, list) or len(rates) != frozen.STEPS:
        raise AuditFailure("INVALID", f"{name}: learning rates must have 48 entries")
    for row in rates:
        if not isinstance(row, dict) or not row:
            raise AuditFailure("INVALID", f"{name}: learning-rate row is empty or malformed")
        for value in row.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise AuditFailure("INVALID", f"{name}: learning rate is nonfinite or malformed")


def validate_observer(name: str, manifest: dict[str, Any], log: str) -> dict[str, Any]:
    enabled = name.endswith("-on")
    declared = manifest.get("launch_spec", {}).get("observer")
    if not isinstance(declared, dict):
        raise AuditFailure("INVALID", f"{name}: observer launch declaration is missing")
    if enabled and declared != frozen.ON_PROFILE:
        raise AuditFailure("INVALID", f"{name}: ON arm did not declare the frozen observer profile")
    if not enabled and declared != {}:
        raise AuditFailure("INVALID", f"{name}: OFF arm declares observer configuration")
    markers = [(match.group(0), match.group(1)) for match in ACTIVATION_RE.finditer(log)]
    roles = {role for _, role in markers}
    if enabled:
        enabled_roles = set(
            ACTIVATION_RE.findall("\n".join(line for line in log.splitlines() if "profiler enabled:" in line))
        )
        started_roles = set(
            ACTIVATION_RE.findall("\n".join(line for line in log.splitlines() if "profiler started:" in line))
        )
        if not {"sender", "collector"}.issubset(enabled_roles) or not {
            "sender",
            "collector",
        }.issubset(started_roles):
            raise AuditFailure("INVALID", f"{name}: ON log lacks sender/collector start and enable evidence")
        enabled_lines = [line for line in log.splitlines() if "profiler enabled:" in line]
        if not any("window=5.0s" in line for line in enabled_lines):
            raise AuditFailure("INVALID", f"{name}: ON log does not confirm the frozen 5s observer window")
    elif markers:
        raise AuditFailure("INVALID", f"{name}: OFF log contains observer activation evidence")
    return {"declared_on": enabled, "activation_roles": sorted(roles), "activation_markers": len(markers)}


def audit_arm(
    raw_root: Path,
    arm_dir: Path,
    name: str,
    lock: dict[str, Any],
    expected_normalized_argv_sha256: str,
    expected_common: dict[str, str],
) -> dict[str, Any]:
    arm_dir = secure_campaign_path(raw_root, arm_dir, f"{name} directory")
    if not arm_dir.is_dir():
        raise AuditFailure("INVALID", f"campaign arm path is not a directory: {arm_dir}")
    manifest_path = arm_dir / "manifest.json"
    log_path = arm_dir / "job.log"
    argv_path = arm_dir / "train-argv.nul"
    manifest_path = secure_campaign_path(raw_root, manifest_path, f"{name}/manifest.json")
    manifest = read_json(manifest_path, f"{name} manifest")
    check_self_hash(manifest, f"{name} manifest")
    if manifest.get("arm") != name or manifest.get("lock_sha256") != lock.get("_self_sha256"):
        raise AuditFailure("INVALID", f"{name}: arm identity or lock binding mismatch")
    for field, expected in expected_common.items():
        if manifest.get(field) != expected:
            raise AuditFailure("INVALID", f"{name}: manifest {field} mismatch")
    if (
        manifest.get("schema") != "TASK11_NATIVE_LOSS_ARM/v1"
        or manifest.get("status") != "SUCCEEDED"
        or manifest.get("valid") is not True
        or manifest.get("resources_returned") is not True
        or manifest.get("save") != 0
        or manifest.get("save_flag_absent") is not True
        or manifest.get("checkpoint_directory_created") is not False
    ):
        raise AuditFailure("INVALID", f"{name}: job, resource-return, or SAVE=0 gate failed")
    log_path = secure_campaign_path(raw_root, log_path, f"{name}/job.log")
    argv_path = secure_campaign_path(raw_root, argv_path, f"{name}/train-argv.nul")
    if require_sha(manifest.get("job_log_sha256"), f"{name}.job_log_sha256") != sha256_file(log_path):
        raise AuditFailure("INVALID", f"{name}: job log hash mismatch")
    argv_hash = require_sha(manifest.get("resolved_argv_sha256"), f"{name}.resolved_argv_sha256")
    if argv_hash != sha256_file(argv_path):
        raise AuditFailure("INVALID", f"{name}: resolved argv hash mismatch")
    argv, normalized = normalize_argv(argv_path.read_bytes())
    if manifest.get("resolved_argv_count") != len(argv):
        raise AuditFailure("INVALID", f"{name}: argv count mismatch")
    if normalized != expected_normalized_argv_sha256:
        raise AuditFailure("INVALID", f"{name}: training argv differs from calibration or another arm")
    source_roots, source_hashes = manifest.get("worker_source_roots"), manifest.get("worker_source_sha256")
    if (
        not isinstance(source_roots, list)
        or not source_roots
        or not isinstance(source_hashes, dict)
        or set(source_roots) != set(source_hashes)
    ):
        raise AuditFailure("INVALID", f"{name}: worker source lineage is missing")
    for root in source_roots:
        require_sha(source_hashes.get(root), f"{name}.worker_source_sha256[{root}]")
        try:
            actual = frozen.source_fingerprint(Path(root))
        except (OSError, ValueError) as exc:
            raise AuditFailure("INCOMPLETE", f"{name}: worker source path unavailable: {root}") from exc
        if actual != lock.get("straggler_source_sha256") or source_hashes[root] != actual:
            raise AuditFailure("INVALID", f"{name}: worker source does not match locked product")
    try:
        parsed = frozen.parse_arm(arm_dir, expected_steps=frozen.STEPS)
    except (OSError, ValueError) as exc:
        raise AuditFailure("INVALID", f"{name}: native log parse failed: {exc}") from exc
    validate_numeric_series(parsed, name)
    # The submitted manifest also records extraction. Compare the values actually
    # re-read from the retained raw log against that embedded copy.
    embedded = manifest.get("native")
    if not isinstance(embedded, dict):
        raise AuditFailure("INVALID", f"{name}: native extraction record is absent")
    for field in (
        "native_step_ids",
        "update_count",
        "token_series",
        "loss_series",
        "grad_norm_series",
        "learning_rate_series",
        "nan_inf_findings",
    ):
        if embedded.get(field) != parsed.get(field):
            raise AuditFailure("INVALID", f"{name}: manifest native {field} differs from raw log")
    log_text = log_path.read_text(errors="replace")
    observer = validate_observer(name, manifest, log_text)
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "job_log_sha256": sha256_file(log_path),
        "resolved_argv_sha256": argv_hash,
        "normalized_argv_sha256": normalized,
        "observer": observer,
        "native": parsed,
    }


def compare_pairs(
    arms: dict[str, dict[str, Any]], tolerances: dict[str, float], pairs: tuple[tuple[str, str], ...]
) -> list[dict[str, Any]]:
    results = []
    for left, right in pairs:
        a, b = arms[left]["native"], arms[right]["native"]
        if (
            a["native_step_ids"] != b["native_step_ids"]
            or a["token_series"] != b["token_series"]
            or a["learning_rate_series"] != b["learning_rate_series"]
            or arms[left]["normalized_argv_sha256"] != arms[right]["normalized_argv_sha256"]
        ):
            raise AuditFailure("INVALID", f"{left}/{right}: pair identity or training inputs differ")
        pair = {"pair": [left, right], "metrics": {}}
        passed = True
        for field in ("loss_series", "grad_norm_series"):
            deltas = [abs(x - y) for x, y in zip(a[field], b[field], strict=True)]
            maximum = max(deltas)
            step = deltas.index(maximum)
            tolerance = tolerances[field]
            within = maximum <= tolerance
            passed &= within
            pair["metrics"][field] = {
                "max_abs_delta": maximum,
                "step": step,
                "tolerance": tolerance,
                "within_envelope": within,
            }
        pair["status"] = "PASS" if passed else "NOT_PASS"
        results.append(pair)
    return results


def audit_campaign(
    repo: Path,
    raw_root: Path,
    calibration_lock_path: Path,
    calibration_result_path: Path,
    measurement_lock_path: Path,
    frozen_verdict_path: Path,
) -> dict[str, Any]:
    calibration_lock = read_json(calibration_lock_path, "calibration lock")
    calibration_result = read_json(calibration_result_path, "calibration result")
    measurement_lock = read_json(measurement_lock_path, "measurement lock")
    frozen_verdict = read_json(frozen_verdict_path, "frozen measurement verdict")
    validate_lock(calibration_lock, "CALIBRATION")
    validate_lock(measurement_lock, "MEASUREMENT")
    if measurement_lock.get("calibration_lock_sha256") != calibration_lock.get("_self_sha256"):
        raise AuditFailure("INVALID", "measurement lock references another calibration lock")
    if sha256_file(calibration_result_path) != measurement_lock.get("calibration_result_sha256"):
        raise AuditFailure("INVALID", "calibration result file hash differs from measurement lock")
    if measurement_lock.get("calibration_result_path") is None:
        raise AuditFailure("INVALID", "measurement lock omits calibration-result path lineage")
    expected_tolerances = validate_calibration_result(calibration_result, calibration_lock, measurement_lock)
    result_commit = measurement_lock["calibration_result_commit"]
    result_rel = Path("evidence/gpu_campaign/task11_3090/native_loss_927c5de/calibration_result.json")
    validate_result_commit(repo, result_commit, result_rel, measurement_lock["calibration_result_sha256"])
    if frozen_verdict.get("_self_sha256") != canonical_sha(frozen_verdict):
        raise AuditFailure("INVALID", "frozen verdict self-hash mismatch")
    if (
        frozen_verdict.get("product_sha") != PRODUCT_SHA
        or frozen_verdict.get("measurement_lock_sha256") != measurement_lock.get("_self_sha256")
        or frozen_verdict.get("calibration_result_sha256") != measurement_lock.get("calibration_result_sha256")
    ):
        raise AuditFailure("INVALID", "frozen verdict lineage mismatch")

    common = {
        "product_sha": PRODUCT_SHA,
        "recipe_sha256": calibration_lock["recipe_sha256"],
        "dataset_sha256": calibration_lock["dataset_sha256"],
        "environment_fingerprint_sha256": calibration_lock["environment_fingerprint_sha256"],
    }
    normalized = require_sha(calibration_result.get("normalized_argv_sha256"), "calibration normalized argv")
    calibration_arms: dict[str, dict[str, Any]] = {}
    for name in CALIBRATION_ARMS:
        arm = audit_arm(
            raw_root,
            raw_root / "calibration" / name,
            name,
            calibration_lock,
            normalized,
            common,
        )
        if arm["manifest_sha256"] != calibration_result["arm_manifests"][name]:
            raise AuditFailure("INVALID", f"{name}: manifest hash differs from calibration result")
        if arm["resolved_argv_sha256"] != calibration_result["raw_argv_sha256"][name]:
            raise AuditFailure("INVALID", f"{name}: raw argv hash differs from calibration result")
        calibration_arms[name] = arm
    calibration_data = {
        name: {
            "manifest_sha256": value["manifest_sha256"],
            "resolved_argv_sha256": value["resolved_argv_sha256"],
            "normalized_argv_sha256": value["normalized_argv_sha256"],
            "loss_series": value["native"]["loss_series"],
            "grad_norm_series": value["native"]["grad_norm_series"],
        }
        for name, value in calibration_arms.items()
    }
    recalculated_calibration = frozen.calibration_result(calibration_lock, calibration_data)
    for field in ("contrasts", "tolerances", "arm_manifests", "raw_argv_sha256", "normalized_argv_sha256"):
        if recalculated_calibration.get(field) != calibration_result.get(field):
            raise AuditFailure("INVALID", f"calibration {field} does not reproduce from the retained OFF logs")

    measurement_arms: dict[str, dict[str, Any]] = {}
    for name in MEASUREMENT_ARMS:
        measurement_arms[name] = audit_arm(
            raw_root,
            raw_root / "measurement" / name,
            name,
            measurement_lock,
            normalized,
            common,
        )
    compared = compare_pairs(measurement_arms, expected_tolerances, EXPECTED_PAIRS)
    status = "PASS_WITHIN_OFF_OFF_ENVELOPE" if all(pair["status"] == "PASS" for pair in compared) else "NOT_PASS"
    expected_frozen = {
        "schema": "TASK11_NATIVE_LOSS_VERDICT/v1",
        "status": status,
        "scope": "Native loss/grad supplement only; not parameter equivalence, accuracy, C1 or overall C2 verdict.",
        "product_sha": PRODUCT_SHA,
        "measurement_lock_sha256": measurement_lock["_self_sha256"],
        "calibration_result_sha256": measurement_lock["calibration_result_sha256"],
        "pairs": [],
        "_self_sha256": None,
    }
    for item in compared:
        left, right = item["pair"]
        expected_frozen["pairs"].append(
            {
                "pair": [left, right],
                "eligible": True,
                "gates": {
                    "step_ids_equal": True,
                    "token_volume_equal": True,
                    "learning_rate_equal": True,
                    "updates_equal": True,
                    "resolved_argv_equal": True,
                },
                "status": item["status"],
                "metrics": item["metrics"],
                "pass": item["status"] == "PASS",
            }
        )
    expected_frozen["_self_sha256"] = canonical_sha(expected_frozen)
    if frozen_verdict != expected_frozen:
        raise AuditFailure("INVALID", "independent eight-arm recomputation differs from the frozen verdict")

    return {
        "status": status,
        "product_sha": PRODUCT_SHA,
        "calibration_lock_sha256": calibration_lock["_self_sha256"],
        "calibration_result_sha256": sha256_file(calibration_result_path),
        "measurement_lock_sha256": measurement_lock["_self_sha256"],
        "frozen_verdict_sha256": sha256_file(frozen_verdict_path),
        "normalized_argv_sha256": normalized,
        "tolerances": expected_tolerances,
        "pairs": compared,
        "calibration_arm_manifest_sha256": {name: arm["manifest_sha256"] for name, arm in calibration_arms.items()},
        "measurement_arm_manifest_sha256": {name: arm["manifest_sha256"] for name, arm in measurement_arms.items()},
        "campaign_file_hashes": {
            name: {
                "manifest_sha256": arm["manifest_sha256"],
                "job_log_sha256": arm["job_log_sha256"],
                "resolved_argv_sha256": arm["resolved_argv_sha256"],
            }
            for name, arm in {**calibration_arms, **measurement_arms}.items()
        },
        "observer_activation": {
            name: arm["observer"] for name, arm in measurement_arms.items() if name.endswith("-on")
        },
        "limitation": "Pass means only that this final-SHA native loss/grad supplement is within its frozen OFF/OFF envelope; it does not establish parameter equivalence, accuracy, C1, or overall C2 acceptance.",
    }


def render_markdown(result: dict[str, Any], tool_sha256: str, raw_root: Path) -> str:
    rows = []
    for pair in result["pairs"]:
        loss = pair["metrics"]["loss_series"]
        grad = pair["metrics"]["grad_norm_series"]
        rows.append(
            f"| {' / '.join(pair['pair'])} | {loss['max_abs_delta']:.12g} / {loss['tolerance']:.12g} | "
            f"{grad['max_abs_delta']:.12g} / {grad['tolerance']:.12g} | {pair['status']} |"
        )
    observer_rows = [
        f"| {name} | {', '.join(value['activation_roles'])} | {value['activation_markers']} |"
        for name, value in result["observer_activation"].items()
    ]
    hash_rows = [
        f"| {name} | `{values['manifest_sha256']}` | `{values['job_log_sha256']}` | "
        f"`{values['resolved_argv_sha256']}` |"
        for name, values in result["campaign_file_hashes"].items()
    ]
    return "\n".join(
        [
            "# Task 11 native loss/grad gate audit — 2026-10-01",
            "",
            f"Status: **{result['status']}**",
            "",
            "The independent read-only audit parsed all four OFF calibration jobs and all four measurement jobs from retained logs. It validated lock hashes and lineage, exact arm order and pairs, per-arm manifest/log/argv hashes, 48 finite contiguous steps, source fingerprints, OFF/ON labels, and runtime observer activation. It then recalculated the OFF envelope and measurement verdict.",
            "",
            f"Product: `{result['product_sha']}`  ",
            f"Calibration lock self-hash: `{result['calibration_lock_sha256']}`  ",
            f"Calibration result file SHA-256: `{result['calibration_result_sha256']}`  ",
            f"Measurement lock self-hash: `{result['measurement_lock_sha256']}`  ",
            f"Frozen verdict file SHA-256: `{result['frozen_verdict_sha256']}`  ",
            f"Normalized argv SHA-256 (only per-arm `--tb-experiment-name` normalized): `{result['normalized_argv_sha256']}`",
            "",
            "| Pair | Loss max Δ / limit | Grad-norm max Δ / limit | Result |",
            "|---|---:|---:|---|",
            *rows,
            "",
            "The limits are twice the maximum observed stepwise delta over the six pairwise contrasts among four OFF calibration arms. Those contrasts share arms and are not independent samples.",
            "",
            "| ON arm | Runtime roles seen | Start/enable markers |",
            "|---|---|---:|",
            *observer_rows,
            "",
            "Runtime logs contain profiler `started` and `enabled` markers for both sender and collector roles, with the frozen 5-second window. The paired OFF logs contain no profiler activation markers.",
            "",
            "| Arm | Manifest SHA-256 | Job-log SHA-256 | Resolved-argv SHA-256 |",
            "|---|---|---|---|",
            *hash_rows,
            "",
            f"Raw campaign root: `{raw_root}`",
            f"Audit tool SHA-256: `{tool_sha256}`",
            "",
            f"Scope: {result['limitation']}",
            "",
            "This is a local evidence replay. Raw jobs, model files, training stack, and Ray runtime remain at their original machine paths; this report does not establish a portable restore or independent backup.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--calibration-lock", type=Path, required=True)
    parser.add_argument("--calibration-result", type=Path, required=True)
    parser.add_argument("--measurement-lock", type=Path, required=True)
    parser.add_argument("--frozen-verdict", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit_campaign(
            args.repo.resolve(),
            args.raw_root.resolve(),
            args.calibration_lock.resolve(),
            args.calibration_result.resolve(),
            args.measurement_lock.resolve(),
            args.frozen_verdict.resolve(),
        )
    except AuditFailure as exc:
        print(json.dumps({"status": exc.status, "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    tool_hash = sha256_file(Path(__file__).resolve())
    report = render_markdown(result, tool_hash, args.raw_root)
    try:
        write_report_once(args.out, report, args.raw_root.resolve())
    except AuditFailure as exc:
        print(json.dumps({"status": exc.status, "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "report": str(args.out), "audit_tool_sha256": tool_hash}))
    return 0 if result["status"] == "PASS_WITHIN_OFF_OFF_ENVELOPE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
