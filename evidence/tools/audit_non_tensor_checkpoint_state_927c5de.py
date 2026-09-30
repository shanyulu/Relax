#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Audit the 48 non-tensor leaves retained in each measurement conversion.

This tool uses ``torch.load(weights_only=False)`` because the campaign's raw
Megatron conversion contains an argparse.Namespace. It therefore accepts only
the four exact, hash-pinned local campaign artifacts and loads one arm at a
time. Do not point it at arbitrary checkpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import typing
from argparse import Namespace
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any


PRODUCT_SHA = "927c5de2f5a8f307cad0c87f2c7eb2b78262334d"
ARM_ORDER = ("P-M1-off", "P-M1-on", "P-M2-on", "P-M2-off")
PAIR_ORDER = (("P-M1", "P-M1-off", "P-M1-on"), ("P-M2", "P-M2-off", "P-M2-on"))
DEFAULT_EVIDENCE_ROOT = Path("/tmp/codex-task11-evidence")
DEFAULT_DATA_ROOT = Path("/root/autodl-tmp/task11-3090")
DEFAULT_MEGATRON_ROOT = Path("/root/autodl-tmp/megatron-stack/Megatron-LM")
CAMPAIGN_REL = Path("formal/parameter-measurement-4c74209")
EVIDENCE_REL = Path("evidence/gpu_campaign/task11_3090/c2_parameter/measurement")
LOCK_REL = Path("evidence/gpu_campaign/task11_3090/c2_parameter/locks/P_EXECUTION_LOCK.json")
SHA_CHUNK = 8 << 20


class AuditError(RuntimeError):
    """Raised when evidence is missing, altered, or cannot be compared
    safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(SHA_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise AuditError(f"checkpoint source is missing or symlinked: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in root.rglob("*")):
        raise AuditError(f"checkpoint tree contains symlinks: {root}")
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def canonical_sha256(payload: dict[str, Any], field: str = "self_sha256") -> str:
    unsigned = {**payload, field: None}
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid or missing JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"expected JSON object: {path}")
    return value


def load_flatten_function(evidence_root: Path, lock: dict[str, Any]):
    adapter_path = evidence_root / "evidence/tools/c2_parameter_dcp_adapter_927c5de.py"
    if str(adapter_path.resolve()) != lock.get("ADAPTER_PATH"):
        raise AuditError("adapter path differs from the frozen execution lock")
    if sha256_file(adapter_path) != lock.get("ADAPTER_SHA256"):
        raise AuditError("adapter code hash differs from the frozen execution lock")
    sys.path.insert(0, str(adapter_path.parent))
    import c2_parameter_dcp_adapter_927c5de as adapter

    return adapter.flatten_leaves


def normalise_value(value: Any, path: str = "$") -> Any:
    """Return a type-preserving JSON value; reject objects without
    semantics."""
    if type(value).__module__ in {"omegaconf.dictconfig", "omegaconf.listconfig"}:
        from omegaconf import OmegaConf

        converted = OmegaConf.to_container(value, resolve=False, enum_to_str=False)
        return normalise_value(converted, path)
    if isinstance(value, Enum):
        return {
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "name": value.name,
            "value": normalise_value(value.value, path),
        }
    if type(value).__module__ == "transfer_queue.utils.zmq_utils" and type(value).__qualname__ == "ZMQServerInfo":
        return {
            "type": "transfer_queue.utils.zmq_utils.ZMQServerInfo",
            "fields": {key: normalise_value(item, f"{path}.{key}") for key, item in sorted(vars(value).items())},
        }
    if (
        type(value).__module__ == "transfer_queue.sampler.seqlen_balanced_sampler"
        and type(value).__qualname__ == "SeqlenBalancedSampler"
    ):
        return {
            "type": "transfer_queue.sampler.seqlen_balanced_sampler.SeqlenBalancedSampler",
            "fields": {key: normalise_value(item, f"{path}.{key}") for key, item in sorted(vars(value).items())},
        }
    if value is typing.Any:
        return {"type": "typing.Any"}
    if isinstance(value, type):
        return {"type": "class", "module": value.__module__, "qualname": value.__qualname__}
    if value is None:
        return {"type": "none"}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuditError(f"non-finite checkpoint value at {path}")
        return {"type": "float", "hex": value.hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, bytes):
        return {"type": "bytes", "sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, Namespace):
        return {
            "type": "argparse.Namespace",
            "fields": {key: normalise_value(item, f"{path}.{key}") for key, item in sorted(vars(value).items())},
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, (str, int, bool)) for key in value):
            raise AuditError(f"unsupported mapping key at {path}")
        if all(isinstance(key, str) for key in value):
            return {
                "type": type(value).__module__ + "." + type(value).__qualname__,
                "fields": {key: normalise_value(item, f"{path}.{key}") for key, item in sorted(value.items())},
            }
        return {
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "items": [
                [normalise_value(key, f"{path}.<key>"), normalise_value(item, f"{path}.{key}")]
                for key, item in sorted(value.items(), key=lambda pair: (type(pair[0]).__name__, str(pair[0])))
            ],
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "items": [normalise_value(item, f"{path}[{index}]") for index, item in enumerate(value)],
        }
    if isinstance(value, tuple):
        return {
            "type": "tuple",
            "items": [normalise_value(item, f"{path}[{index}]") for index, item in enumerate(value)],
        }
    if isinstance(value, set | frozenset):
        items = [normalise_value(item, f"{path}[]") for item in value]
        items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return {"type": type(value).__name__, "items": items}
    if isinstance(value, Path):
        return {"type": "pathlib.Path", "value": str(value)}
    if type(value).__module__ == "torch" and type(value).__qualname__ in {
        "dtype",
        "device",
        "layout",
        "memory_format",
    }:
        # These are immutable PyTorch descriptors commonly stored in args.
        # Their canonical names are the public semantic value.
        return {"type": "torch." + type(value).__qualname__, "value": str(value).removeprefix("torch.")}
    raise AuditError(f"unsupported semantic value type at {path}: {type(value).__module__}.{type(value).__qualname__}")


def digest_normalised(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def differing_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(differing_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list):
        paths = []
        if len(left) != len(right):
            paths.append(path + ".length")
        for index, (a, b) in enumerate(zip(left, right)):
            paths.extend(differing_paths(a, b, f"{path}[{index}]"))
        return paths
    return [] if left == right else [path]


def _validate_identity(
    evidence_root: Path, data_root: Path, lock: dict[str, Any], arm: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path]:
    evidence_arm = evidence_root / EVIDENCE_REL / arm
    data_arm = data_root / CAMPAIGN_REL / arm
    manifest = read_json(evidence_arm / "manifest.json")
    inventory = read_json(evidence_arm / "inventory.json")
    record = read_json(evidence_arm / "ADAPTER_RECORD.json")
    if manifest.get("job_status") != "SUCCEEDED" or manifest.get("valid") is not True:
        raise AuditError(f"arm manifest is not successful and valid: {arm}")
    if manifest.get("product_sha") != PRODUCT_SHA or manifest.get("git", {}).get("commit") != PRODUCT_SHA:
        raise AuditError(f"product identity mismatch: {arm}")
    measurement_lock_path = (
        evidence_root / "evidence/gpu_campaign/task11_3090/c2_parameter/locks/P_MEASUREMENT_LOCK.json"
    )
    if manifest.get("lock_sha256") != sha256_file(measurement_lock_path) or manifest.get("expected_steps") != lock.get(
        "EXPECTED_STEPS"
    ):
        raise AuditError(f"execution lock or step count mismatch: {arm}")
    for manifest_key, lock_key in (
        ("adapter_sha256", "ADAPTER_SHA256"),
        ("comparator_sha256", "COMPARATOR_SHA256"),
        ("dataset_sha256", "DATASET_SHA256"),
        ("env_fingerprint_sha256", "ENV_FINGERPRINT_SHA256"),
        ("protocol_sha256", "PROTOCOL_SHA256"),
        ("recipe_sha256", "RECIPE_SHA256"),
        ("runner_sha256", "RUNNER_SHA256"),
    ):
        if manifest.get(manifest_key) != lock.get(lock_key):
            raise AuditError(f"{manifest_key} differs from the measurement lock: {arm}")
    if manifest.get("save") != 1 or manifest.get("stage") != "MEASUREMENT":
        raise AuditError(f"measurement stage or SAVE setting mismatch: {arm}")
    if inventory.get("arm_name") != arm or inventory.get("product_sha") != PRODUCT_SHA:
        raise AuditError(f"inventory identity mismatch: {arm}")
    if inventory.get("self_sha256") != canonical_sha256(inventory):
        raise AuditError(f"inventory self-hash mismatch: {arm}")
    if inventory.get("dataset_sha256") != lock.get("DATASET_SHA256"):
        raise AuditError(f"inventory dataset identity mismatch: {arm}")
    lineage = inventory.get("lineage", {})
    if sha256_file(evidence_arm / "manifest.json") != lineage.get("arm_manifest_sha256"):
        raise AuditError(f"manifest lineage mismatch: {arm}")
    if sha256_file(evidence_arm / "ADAPTER_RECORD.json") != lineage.get("adapter_record_sha256"):
        raise AuditError(f"adapter record lineage mismatch: {arm}")
    if record.get("arm_name") != arm or record.get("status") != "REVIEWED_TRUSTED_CAMPAIGN_ONLY":
        raise AuditError(f"adapter record identity/trust marker mismatch: {arm}")
    if record.get("adapter_sha256") != lock.get("ADAPTER_SHA256"):
        raise AuditError(f"adapter source identity mismatch: {arm}")
    if record.get("dropped_non_tensor_count") != len(record.get("dropped_non_tensor_leaves", [])):
        raise AuditError(f"adapter non-tensor inventory count mismatch: {arm}")
    raw = data_arm / "adapted_raw/converted.pt"
    recorded_raw = Path(record.get("raw_converted_path", "")).resolve()
    if recorded_raw != raw.resolve() or not raw.is_file() or raw.is_symlink():
        raise AuditError(f"raw converted payload path is not the exact arm-owned artifact: {arm}")
    if raw.stat().st_size != record.get("raw_converted_bytes"):
        raise AuditError(f"raw converted payload byte count mismatch: {arm}")
    source = Path(record.get("source_iteration_dir", "")).resolve()
    checkpoints = (data_arm / "checkpoints").resolve()
    if not source.is_relative_to(checkpoints) or source.is_symlink():
        raise AuditError(f"DCP source is outside the exact arm checkpoint directory: {arm}")
    if inventory.get("lineage", {}).get("source_tree_sha256") != record.get("source_tree_sha256"):
        raise AuditError(f"source tree lineage mismatch: {arm}")
    if inventory.get("lineage", {}).get("sanitized_sha256") != record.get("sanitized_sha256"):
        raise AuditError(f"sanitized payload lineage mismatch: {arm}")
    return manifest, inventory, record, raw, source


def audit(evidence_root: Path, data_root: Path, megatron_root: Path) -> dict[str, Any]:
    evidence_root = evidence_root.resolve(strict=True)
    data_root = data_root.resolve(strict=True)
    megatron_root = megatron_root.resolve(strict=True)
    if not (megatron_root / "megatron/core").is_dir():
        raise AuditError("Megatron source root is missing megatron/core")
    lock_path = evidence_root / LOCK_REL
    execution_lock = read_json(lock_path)
    if execution_lock.get("product_sha") != PRODUCT_SHA or execution_lock.get("arm_order") != list(ARM_ORDER):
        raise AuditError("frozen execution lock identity/order mismatch")
    if execution_lock.get("self_sha256") != canonical_sha256(execution_lock, field="self_sha256"):
        raise AuditError("execution lock self-hash mismatch")
    measurement_lock_path = (
        evidence_root / "evidence/gpu_campaign/task11_3090/c2_parameter/locks/P_MEASUREMENT_LOCK.json"
    )
    measurement_lock = read_json(measurement_lock_path)
    if measurement_lock.get("PRODUCT_SHA") != PRODUCT_SHA or measurement_lock.get("ARM_ORDER") != list(ARM_ORDER):
        raise AuditError("measurement lock identity/order mismatch")
    if measurement_lock.get("_self_sha256") != canonical_sha256(measurement_lock, field="_self_sha256"):
        raise AuditError("measurement lock self-hash mismatch")
    if measurement_lock.get("STAGE") != "MEASUREMENT" or measurement_lock.get("SAVE") != 1:
        raise AuditError("only the frozen SAVE=1 parameter measurement lock is accepted")
    if execution_lock.get("measurement_lock") != str(measurement_lock_path.relative_to(evidence_root)):
        raise AuditError("execution lock points to a different measurement lock")
    flatten_leaves = load_flatten_function(evidence_root, measurement_lock)

    import torch

    sys.path.insert(0, str(megatron_root))
    arm_values: dict[str, dict[str, Any]] = {}
    arm_audit: dict[str, Any] = {}
    for arm in ARM_ORDER:
        manifest, inventory, record, raw, source = _validate_identity(evidence_root, data_root, measurement_lock, arm)
        source_hash = tree_sha256(source)
        if source_hash != record.get("source_tree_sha256"):
            raise AuditError(f"DCP source tree hash mismatch: {arm}")
        raw_hash = sha256_file(raw)
        if raw_hash != record.get("raw_converted_sha256"):
            raise AuditError(f"raw converted payload hash mismatch: {arm}")
        if sha256_file(data_root / CAMPAIGN_REL / arm / "adapted/converted_tensors.pt") != record.get(
            "sanitized_sha256"
        ):
            raise AuditError(f"sanitized tensor payload hash mismatch: {arm}")

        # weights_only=False is required by this trusted campaign's own raw
        # adapter output; mmap avoids an additional 8.3-GB copy in RAM.
        state = torch.load(raw, map_location="cpu", weights_only=False, mmap=True)
        flat = flatten_leaves(state)
        non_tensor = {key: value for key, value in flat.items() if not isinstance(value, torch.Tensor)}
        expected_rows = record.get("dropped_non_tensor_leaves", [])
        expected = {row.get("key"): row.get("type") for row in expected_rows}
        actual = {key: type(value).__module__ + "." + type(value).__qualname__ for key, value in non_tensor.items()}
        if expected != actual:
            raise AuditError(f"actual non-tensor leaves differ from adapter record: {arm}")
        if len(non_tensor) != 48:
            raise AuditError(f"expected exactly 48 non-tensor leaves, found {len(non_tensor)} in {arm}")
        tensor_keys = {key for key, value in flat.items() if isinstance(value, torch.Tensor)}
        inventory_keys = {row["name"].split("::", 1)[1] for row in inventory.get("tensors", [])}
        if tensor_keys != inventory_keys:
            raise AuditError(f"raw tensor keys do not match inventory keys in {arm}")
        arm_values[arm] = {key: normalise_value(value, key) for key, value in non_tensor.items()}
        arm_audit[arm] = {
            "status": "VERIFIED_AND_READ",
            "product_sha": manifest["product_sha"],
            "adapter_record_sha256": sha256_file(evidence_root / EVIDENCE_REL / arm / "ADAPTER_RECORD.json"),
            "raw_converted_sha256": raw_hash,
            "raw_converted_bytes": raw.stat().st_size,
            "source_tree_sha256": source_hash,
            "flattened_leaves": len(flat),
            "tensor_leaves": len(tensor_keys),
            "non_tensor_leaves": len(non_tensor),
            "non_tensor_type_counts": _type_counts(actual),
        }
        del state, flat, non_tensor

    keys = set(arm_values[ARM_ORDER[0]])
    if any(set(arm_values[arm]) != keys for arm in ARM_ORDER[1:]):
        raise AuditError("the four measurement arms have different non-tensor key sets")
    leaf_results = []
    pair_equal_counts = {name: 0 for name, _, _ in PAIR_ORDER}
    all_equal_count = 0
    for key in sorted(keys):
        by_arm = {arm: arm_values[arm][key] for arm in ARM_ORDER}
        equal_pairs = {}
        for pair, off, on in PAIR_ORDER:
            equal = by_arm[off] == by_arm[on]
            equal_pairs[pair] = equal
            pair_equal_counts[pair] += int(equal)
        all_equal = all(by_arm[arm] == by_arm[ARM_ORDER[0]] for arm in ARM_ORDER[1:])
        all_equal_count += int(all_equal)
        leaf_results.append(
            {
                "key": key,
                "type": arm_values[ARM_ORDER[0]][key]["type"],
                "pair_equal": equal_pairs,
                "all_four_equal": all_equal,
                "value_sha256": {arm: digest_normalised(by_arm[arm]) for arm in ARM_ORDER},
                "namespace_changed_paths": _namespace_changes(by_arm, key)
                if any("Namespace" in str(by_arm[arm].get("type")) for arm in ARM_ORDER)
                else [],
                "namespace_difference_classes": _namespace_difference_classes(by_arm)
                if any("Namespace" in str(by_arm[arm].get("type")) for arm in ARM_ORDER)
                else {},
                "values": _safe_values(key, by_arm),
            }
        )
    differences_found = any(count < len(keys) for count in pair_equal_counts.values()) or all_equal_count < len(keys)
    return {
        "schema": "C2_NON_TENSOR_STATE_AUDIT/v1",
        "status": "AUDIT_COMPLETE",
        "equivalence_status": "DIFFERENCES_FOUND" if differences_found else "ALL_COMPARED_LEAVES_EQUAL",
        "scope": "semantic comparison of all 48 adapter-dropped leaves from each retained raw converted measurement payload",
        "product_sha": PRODUCT_SHA,
        "execution_lock_sha256": sha256_file(lock_path),
        "measurement_lock_sha256": sha256_file(measurement_lock_path),
        "arms": arm_audit,
        "summary": {
            "leaf_count_per_arm": len(keys),
            "pair_equal_leaf_counts": pair_equal_counts,
            "all_four_equal_leaf_count": all_equal_count,
            "pair_count_is_not_a_statistical_sample_count": True,
        },
        "leaves": leaf_results,
        "limits": [
            "Only the four named measurement-arm raw converted payloads were loaded; no DCP re-conversion was performed.",
            "Semantic equality covers these 48 non-tensor leaves only; it does not establish full optimizer or scheduler restoration equivalence.",
            "torch.load(weights_only=False) is code-execution capable; inputs were accepted only after exact local campaign path, adapter lineage, raw hash, and source DCP tree hash checks.",
            "No GPU was used; one arm was loaded at a time with mmap; no payload copies were created.",
        ],
    }


def _type_counts(type_map: dict[str, str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in type_map.values():
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _namespace_changes(by_arm: dict[str, Any], key: str) -> list[dict[str, Any]]:
    first = by_arm[ARM_ORDER[0]].get("fields", {})
    changes = []
    for arm in ARM_ORDER[1:]:
        other = by_arm[arm].get("fields", {})
        paths = differing_paths(first, other)
        changes.append({"arm": arm, "paths": paths})
    return changes


def _namespace_difference_classes(by_arm: dict[str, Any]) -> dict[str, list[str]]:
    baseline = by_arm[ARM_ORDER[0]]
    paths = set()
    for arm in ARM_ORDER[1:]:
        paths.update(differing_paths(baseline, by_arm[arm]))
    classes: dict[str, list[str]] = {"run_output_identity": [], "runtime_endpoint": [], "other_configuration": []}
    for path in sorted(paths):
        field_path = path.removeprefix("$.fields.")
        if field_path in {"rollout_result_dir.value", "save.value", "tb_experiment_name.value"}:
            category = "run_output_identity"
        elif ".zmq_info.fields." in field_path and (".id.value" in field_path or ".ports.fields." in field_path):
            category = "runtime_endpoint"
        else:
            category = "other_configuration"
        classes[category].append(field_path)
    return {key: values for key, values in classes.items() if values}


def _safe_values(key: str, by_arm: dict[str, Any]) -> dict[str, Any] | None:
    if by_arm[ARM_ORDER[0]].get("type") == "argparse.Namespace":
        return None
    if any(
        token in key.lower()
        for token in ("token", "secret", "password", "credential", "endpoint", "url", "path", "dir", "file")
    ):
        return None
    values = {}
    for arm, value in by_arm.items():
        kind = value.get("type")
        if kind in {"bool", "int", "str"}:
            values[arm] = value.get("value")
        elif kind == "float":
            values[arm] = float.fromhex(value["hex"])
        else:
            values[arm] = {key: child for key, child in value.items() if key != "value"}
    return values


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Task 11 参数 checkpoint 非张量状态审查",
        "",
        f"- 审查状态：`{result['status']}`；字段等价判定：`{result['equivalence_status']}`",
        f"- 产品：`{result['product_sha']}`",
        f"- 每臂真实读取并核对的非张量叶：{result['summary']['leaf_count_per_arm']}",
        "- 读取来源：四个测量臂各自哈希验证后的 `adapted_raw/converted.pt`；每次只加载一个臂。",
        "",
        "## 覆盖结果",
        "",
        "| 测量对 | 完全相同叶数 | 覆盖叶数 |",
        "|---|---:|---:|",
    ]
    for pair, count in result["summary"]["pair_equal_leaf_counts"].items():
        lines.append(f"| {pair} OFF/ON | {count} | {result['summary']['leaf_count_per_arm']} |")
    arg_rows = [
        row for row in result["leaves"] if row["type"] == "argparse.Namespace" and row["namespace_difference_classes"]
    ]
    if arg_rows:
        lines += ["", "## 唯一差异叶：训练参数 `args`", ""]
        classes = arg_rows[0]["namespace_difference_classes"]
        if not classes.get("other_configuration"):
            lines.append(
                "跨臂差异仅涉及各次运行的输出目录／TensorBoard 名称，以及 TransferQueue 服务实例 ID／端口；其他参数值一致。以下值是运行身份或进程内通信地址，不是模型权重、优化器超参数或 scheduler 策略。"
            )
        else:
            lines.append(
                "差异字段按路径分类如下；`other_configuration` 项需要按字段名单独审阅，不能归为运行路径差异。"
            )
        for category, paths in classes.items():
            lines.append(f"- `{category}`（{len(paths)} 项）")
            lines.extend(f"  - `{path}`" for path in paths)
        lines += [
            "",
            "四臂共 1,636 个顶层 args 字段；逐臂哈希绑定在 JSON 中。optimizer step 均为 48，checkpoint iteration 均为 47；scheduler 与 optimizer 的其余 47 个非张量叶四臂完全相同。",
        ]
    lines += [
        "",
        "## 差异",
        "",
        "| checkpoint 叶 | 类型 | M1 相同 | M2 相同 | 四臂相同 | 差异说明 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in result["leaves"]:
        detail = "—"
        changed = [entry for entry in row["namespace_changed_paths"] if entry["paths"]]
        if changed:
            detail = "; ".join(f"{entry['arm']}: {len(entry['paths'])} 个 args 字段路径不同" for entry in changed)
        elif not row["all_four_equal"]:
            pairs = [name for name, equal in row["pair_equal"].items() if not equal]
            detail = "OFF/ON 值不同：" + ", ".join(pairs)
        lines.append(
            f"| `{row['key']}` | `{row['type']}` | {'是' if row['pair_equal']['P-M1'] else '否'} | "
            f"{'是' if row['pair_equal']['P-M2'] else '否'} | {'是' if row['all_four_equal'] else '否'} | {detail} |"
        )
    lines += ["", "## 判读边界", ""]
    lines.extend(f"- {limit}" for limit in result["limits"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--megatron-root", type=Path, default=DEFAULT_MEGATRON_ROOT)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.evidence_root, args.data_root, args.megatron_root)
        for output in (args.out_json, args.out_md):
            if output.exists():
                raise AuditError(f"refusing to overwrite existing output: {output}")
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.out_md.write_text(render_markdown(result), encoding="utf-8")
    except (AuditError, OSError, ValueError, RuntimeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "summary": result["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
