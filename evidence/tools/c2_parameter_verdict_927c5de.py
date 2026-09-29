#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Frozen C2 parameter-equivalence verdict for build 927c5de.

The command consumes a self-hashed, committed calibration JSON and exactly two
ON/OFF pair manifests.  Each pair manifest binds the calibration file hash,
product SHA, protocol SHA, and two retained checkpoint inventory JSON files.
An inventory contains one entry per tensor with ``name``, ``shape``, ``dtype``
and either an inline flat ``values`` array or a C-order ``.npy`` payload.

This comparator deliberately has no GPU, torch, or numpy dependency.  It is a
post-run evidence gate: a missing retained input is INCOMPLETE, identity drift
or malformed evidence is INVALID, and a frozen-tolerance breach is NOT_PASS.
It never overwrites its self-hashed result.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"[0-9a-f]{64}")
SHA1_RE = re.compile(r"[0-9a-f]{40}")
FLOAT_DTYPES = {"<f2", "<f4", "<f8", ">f2", ">f4", ">f8", "bfloat16"}
NPY_TYPES = {
    "|b1": ("?", 1, False),
    "|u1": ("B", 1, False),
    "|i1": ("b", 1, False),
    "<u2": ("H", 2, False),
    ">u2": ("H", 2, True),
    "<i2": ("h", 2, False),
    ">i2": ("h", 2, True),
    "<u4": ("I", 4, False),
    ">u4": ("I", 4, True),
    "<i4": ("i", 4, False),
    ">i4": ("i", 4, True),
    "<u8": ("Q", 8, False),
    ">u8": ("Q", 8, True),
    "<i8": ("q", 8, False),
    ">i8": ("q", 8, True),
    "<f2": ("e", 2, False),
    ">f2": ("e", 2, True),
    "<f4": ("f", 4, False),
    ">f4": ("f", 4, True),
    "<f8": ("d", 8, False),
    ">f8": ("d", 8, True),
}


class IncompleteError(Exception):
    """A required retained artifact or payload is absent."""


class InvalidError(Exception):
    """An input is malformed, tampered, or bound to the wrong experiment."""


@dataclass(frozen=True)
class Tensor:
    name: str
    shape: tuple[int, ...]
    dtype: str
    values: tuple[Any, ...]


def canonical_sha256(payload: dict[str, Any]) -> str:
    unsigned = {**payload, "self_sha256": None}
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise IncompleteError(f"missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidError(f"{label} is not a JSON object: {path}")
    return payload


def require_sha(value: Any, label: str, *, size: int = 64) -> str:
    value = str(value)
    pattern = SHA256_RE if size == 64 else SHA1_RE
    if not pattern.fullmatch(value):
        raise InvalidError(f"invalid {label}")
    return value


def resolve_relative(base: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise IncompleteError(f"missing {label}")
    target = (base / value).resolve()
    if not target.is_relative_to(base.resolve()):
        raise InvalidError(f"{label} escapes its manifest directory")
    return target


def value_count(shape: tuple[int, ...]) -> int:
    count = 1
    for size in shape:
        if type(size) is not int or size < 0:
            raise InvalidError("tensor shape has a non-negative integer requirement")
        count *= size
    return count


def normalize_dtype(dtype: Any) -> str:
    if not isinstance(dtype, str) or not dtype:
        raise InvalidError("tensor dtype is missing")
    aliases = {
        "bool": "|b1",
        "uint8": "|u1",
        "int8": "|i1",
        "uint16": "<u2",
        "int16": "<i2",
        "uint32": "<u4",
        "int32": "<i4",
        "uint64": "<u8",
        "int64": "<i8",
        "float16": "<f2",
        "float32": "<f4",
        "float64": "<f8",
        "bfloat16": "bfloat16",
    }
    return aliases.get(dtype, dtype)


def read_npy(path: Path) -> tuple[str, tuple[int, ...], tuple[Any, ...]]:
    if not path.is_file():
        raise IncompleteError(f"missing tensor payload: {path}")
    raw = path.read_bytes()
    if raw[:6] != b"\x93NUMPY" or len(raw) < 10:
        raise InvalidError(f"unsupported npy payload: {path}")
    major = raw[6]
    if major == 1:
        header_length = struct.unpack("<H", raw[8:10])[0]
        offset = 10
    elif major in (2, 3):
        if len(raw) < 12:
            raise InvalidError(f"truncated npy header: {path}")
        header_length = struct.unpack("<I", raw[8:12])[0]
        offset = 12
    else:
        raise InvalidError(f"unsupported npy version {major}: {path}")
    try:
        header = ast.literal_eval(raw[offset : offset + header_length].decode("latin1"))
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        raise InvalidError(f"invalid npy header: {path}") from exc
    if not isinstance(header, dict) or header.get("fortran_order"):
        raise InvalidError(f"npy payload must be C-order: {path}")
    dtype = normalize_dtype(header.get("descr"))
    if dtype not in NPY_TYPES:
        raise InvalidError(f"unsupported npy dtype {dtype}: {path}")
    shape_raw = header.get("shape")
    if not isinstance(shape_raw, tuple):
        raise InvalidError(f"invalid npy shape: {path}")
    shape = tuple(shape_raw)
    count = value_count(shape)
    code, width, big_endian = NPY_TYPES[dtype]
    data = raw[offset + header_length :]
    if len(data) != count * width:
        raise InvalidError(f"npy size does not match shape: {path}")
    endian = ">" if big_endian else "<"
    if width == 1:
        endian = ""
    try:
        values = struct.unpack(f"{endian}{count}{code}", data) if count else ()
    except struct.error as exc:
        raise InvalidError(f"invalid npy values: {path}") from exc
    return dtype, shape, values


def read_inventory(path: Path, *, product_sha: str, protocol_sha256: str) -> dict[str, Tensor]:
    inventory = load_json(path, "checkpoint inventory")
    if inventory.get("product_sha") != product_sha or inventory.get("protocol_sha256") != protocol_sha256:
        raise InvalidError(f"checkpoint inventory identity mismatch: {path}")
    tensors = inventory.get("tensors")
    if not isinstance(tensors, list) or not tensors:
        raise IncompleteError(f"checkpoint inventory has no tensors: {path}")
    output: dict[str, Tensor] = {}
    for entry in tensors:
        if not isinstance(entry, dict):
            raise InvalidError(f"invalid tensor entry in {path}")
        name = entry.get("name")
        if not isinstance(name, str) or not name or name in output:
            raise InvalidError(f"missing or duplicate tensor name in {path}")
        shape_raw = entry.get("shape")
        if not isinstance(shape_raw, list):
            raise InvalidError(f"missing tensor shape for {name}")
        shape = tuple(shape_raw)
        count = value_count(shape)
        dtype = normalize_dtype(entry.get("dtype"))
        if "values" in entry:
            values_raw = entry["values"]
            if not isinstance(values_raw, list) or len(values_raw) != count:
                raise IncompleteError(f"missing or incomplete values for tensor {name}")
            values = tuple(values_raw)
        elif "npy" in entry:
            payload = resolve_relative(path.parent, entry["npy"], f"npy payload for {name}")
            npy_dtype, npy_shape, values = read_npy(payload)
            # NumPy has no portable bf16 scalar descriptor.  The exporter
            # stores the exact CPU bf16 values converted to float32, while the
            # inventory preserves the model dtype for topology comparison.
            representation = normalize_dtype(entry.get("payload_dtype", dtype))
            if npy_dtype != representation or npy_shape != shape or (dtype != representation and dtype != "bfloat16"):
                raise InvalidError(f"npy metadata differs from inventory for tensor {name}")
        else:
            raise IncompleteError(f"missing payload for tensor {name}")
        if dtype in FLOAT_DTYPES:
            try:
                if not all(math.isfinite(float(value)) for value in values):
                    raise InvalidError(f"non-finite floating tensor {name}")
            except (TypeError, ValueError) as exc:
                raise InvalidError(f"non-numeric floating tensor {name}") from exc
        output[name] = Tensor(name=name, shape=shape, dtype=dtype, values=values)
    return output


def read_calibration(path: Path) -> tuple[dict[str, Any], str]:
    calibration = load_json(path, "calibration")
    if calibration.get("status") != "FROZEN_OFF_ONLY":
        raise InvalidError("calibration is not frozen")
    require_sha(calibration.get("product_sha"), "calibration product_sha", size=40)
    require_sha(calibration.get("protocol_sha256"), "calibration protocol_sha256")
    if calibration.get("self_sha256") != canonical_sha256(calibration):
        raise InvalidError("calibration self hash mismatch")
    tolerances = calibration.get("tensor_tolerances")
    if not isinstance(tolerances, dict) or not tolerances:
        raise IncompleteError("calibration has no per-tensor tolerance table")
    for name, tolerance in tolerances.items():
        if (
            not isinstance(name, str)
            or type(tolerance) not in (int, float)
            or tolerance < 0
            or not math.isfinite(tolerance)
        ):
            raise InvalidError("invalid per-tensor calibration tolerance")
    return calibration, file_sha256(path)


def compare_pair(
    pair_path: Path, calibration: dict[str, Any], calibration_sha: str
) -> tuple[dict[str, Any], list[str]]:
    pair = load_json(pair_path, "pair manifest")
    product_sha = calibration["product_sha"]
    protocol_sha256 = calibration["protocol_sha256"]
    if pair.get("product_sha") != product_sha or pair.get("protocol_sha256") != protocol_sha256:
        raise InvalidError(f"pair identity mismatch: {pair_path}")
    if pair.get("calibration_sha256") != calibration_sha:
        raise InvalidError(f"pair does not bind the supplied calibration: {pair_path}")
    pair_id = pair.get("pair_id")
    if not isinstance(pair_id, str) or not pair_id:
        raise InvalidError(f"missing pair_id: {pair_path}")
    off_path = resolve_relative(pair_path.parent, pair.get("off_inventory"), f"OFF inventory for {pair_id}")
    on_path = resolve_relative(pair_path.parent, pair.get("on_inventory"), f"ON inventory for {pair_id}")
    off = read_inventory(off_path, product_sha=product_sha, protocol_sha256=protocol_sha256)
    on = read_inventory(on_path, product_sha=product_sha, protocol_sha256=protocol_sha256)
    tolerances = calibration["tensor_tolerances"]
    violations: list[str] = []
    missing_tolerances: list[str] = []
    tensor_results: dict[str, Any] = {}
    if set(off) != set(on):
        violations.append("tensor key set differs")
    for name in sorted(set(off) | set(on)):
        if name not in off or name not in on:
            tensor_results[name] = {"state": "MISSING_FROM_ONE_ARM"}
            continue
        left, right = off[name], on[name]
        if left.shape != right.shape or left.dtype != right.dtype:
            violations.append(f"{name}: shape or dtype differs")
            tensor_results[name] = {
                "state": "METADATA_MISMATCH",
                "off": {"shape": left.shape, "dtype": left.dtype},
                "on": {"shape": right.shape, "dtype": right.dtype},
            }
            continue
        if left.dtype in FLOAT_DTYPES and name not in tolerances:
            missing_tolerances.append(name)
            tensor_results[name] = {"state": "MISSING_FROZEN_TOLERANCE"}
            continue
        if left.dtype in FLOAT_DTYPES:
            absolute = [abs(float(a) - float(b)) for a, b in zip(left.values, right.values)]
            relative = [
                delta / max(abs(float(a)), abs(float(b)), sys.float_info.min)
                for a, b, delta in zip(left.values, right.values, absolute)
            ]
            maximum = max(absolute, default=0.0)
            tolerance = tolerances[name]
            within = maximum <= tolerance
            tensor_results[name] = {
                "state": "PASS" if within else "NOT_PASS",
                "max_abs_delta": maximum,
                "max_rel_delta": max(relative, default=0.0),
                "tolerance": tolerance,
                "exact_equal": left.values == right.values,
            }
            if not within:
                violations.append(f"{name}: {maximum} > {tolerance}")
        else:
            exact = left.values == right.values
            tensor_results[name] = {"state": "PASS" if exact else "NOT_PASS", "exact_equal": exact}
            if not exact:
                violations.append(f"{name}: non-floating payload differs")
    return {
        "pair_id": pair_id,
        "manifest_sha256": file_sha256(pair_path),
        "off_inventory_sha256": file_sha256(off_path),
        "on_inventory_sha256": file_sha256(on_path),
        "tensors": tensor_results,
        "violations": violations,
        "missing_tolerances": missing_tolerances,
    }, violations


def result_payload(
    verdict: str, reason: str | None, *, calibration: Path | None, pairs: list[dict[str, Any]]
) -> dict[str, Any]:
    result = {
        "schema_version": 1,
        "verdict": verdict,
        "reason": reason,
        "scope": "final retained checkpoint parameter equivalence only; loss, updates, tokens, and overlap are separate gates",
        "calibration_path": str(calibration) if calibration else None,
        "calibration_sha256": file_sha256(calibration) if calibration and calibration.is_file() else None,
        "pairs": pairs,
        "self_sha256": None,
    }
    result["self_sha256"] = canonical_sha256(result)
    return result


def run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise SystemExit("refusing to overwrite an existing parameter verdict")
    calibration_path = Path(args.calibration)
    pairs: list[dict[str, Any]] = []
    try:
        if len(args.pair_manifest) != 2:
            raise InvalidError("exactly two ON/OFF pair manifests are required")
        calibration, calibration_sha = read_calibration(calibration_path)
        seen_ids: set[str] = set()
        all_violations: list[str] = []
        for raw_pair in args.pair_manifest:
            pair, violations = compare_pair(Path(raw_pair), calibration, calibration_sha)
            if pair["pair_id"] in seen_ids:
                raise InvalidError(f"duplicate pair_id {pair['pair_id']}")
            seen_ids.add(pair["pair_id"])
            pairs.append(pair)
            all_violations.extend(f"{pair['pair_id']}: {item}" for item in violations)
        missing = [name for pair in pairs for name in pair["missing_tolerances"]]
        verdict = "NOT_PASS" if all_violations else ("INCOMPLETE" if missing else "PASS")
        reason = (
            "; ".join(all_violations or ([f"missing tolerances: {', '.join(missing)}"] if missing else [])) or None
        )
    except IncompleteError as exc:
        verdict, reason = "INCOMPLETE", str(exc)
    except InvalidError as exc:
        verdict, reason = "INVALID", str(exc)
    result = result_payload(verdict, reason, calibration=calibration_path, pairs=pairs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"C2 parameter verdict: {verdict}; result sha256 {result['self_sha256']}")
    return 0 if verdict == "PASS" else (2 if verdict == "INVALID" else 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, help="self-hashed frozen calibration JSON")
    parser.add_argument(
        "--pair-manifest", required=True, action="append", help="ON/OFF pair manifest; provide exactly twice"
    )
    parser.add_argument("--out", required=True, help="new self-hashed verdict JSON")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
