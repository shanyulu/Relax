#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Safely export retained torch checkpoints into C2 tensor inventories.

Only ordinary torch checkpoint mappings are accepted.  Megatron DCP shards,
pickle-only files, missing trees, and unknown layouts return INCOMPLETE with a
specific reason; they are never deserialized speculatively.  Torch is imported
only when this post-run CPU tool is invoked and always uses ``weights_only``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def self_hash(payload: dict[str, Any]) -> str:
    unsigned = {**payload, "self_sha256": None}
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            result.update(_flatten(value[key], f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}[{index}]"))
    else:
        result[prefix] = value
    return result


def _dtype_spec(tensor: Any) -> tuple[str, str]:
    import torch

    mapping = {
        torch.bool: ("bool", "|b1"),
        torch.uint8: ("uint8", "|u1"),
        torch.int8: ("int8", "|i1"),
        torch.int16: ("int16", "<i2"),
        torch.int32: ("int32", "<i4"),
        torch.int64: ("int64", "<i8"),
        torch.float16: ("float16", "<f2"),
        torch.float32: ("float32", "<f4"),
        torch.float64: ("float64", "<f8"),
        # NumPy has no portable bf16 descriptor.  Values are therefore stored
        # as canonical float32 while the inventory preserves source dtype.
        torch.bfloat16: ("bfloat16", "<f4"),
    }
    try:
        return mapping[tensor.dtype]
    except KeyError as exc:
        raise ValueError(f"unsupported tensor dtype: {tensor.dtype}") from exc


def _npy(path: Path, tensor: Any, representation: str) -> None:
    import torch

    tensor = tensor.detach().cpu().contiguous()
    if representation == "<f4" and tensor.dtype == torch.bfloat16:
        tensor = tensor.to(torch.float32)
    raw = tensor.view(torch.uint8).flatten()
    shape = tuple(int(size) for size in tensor.shape)
    header = repr({"descr": representation, "fortran_order": False, "shape": shape}).encode("latin1")
    padding = (16 - ((10 + len(header) + 1) % 16)) % 16
    header += b" " * padding + b"\n"
    with path.open("wb") as output:
        output.write(b"\x93NUMPY" + bytes((1, 0)) + struct.pack("<H", len(header)) + header)
        # Avoid a giant Python byte list while preserving exact CPU bytes.
        for offset in range(0, raw.numel(), 1 << 20):
            output.write(bytes(raw[offset : offset + (1 << 20)].tolist()))


def export_inventory(checkpoint: Path, out: Path, *, identity: dict[str, Any], arm_name: str) -> dict[str, Any]:
    """Export supported tensors and retain content/tree provenance."""
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("INCOMPLETE: torch is required for CPU checkpoint export") from exc
    if not checkpoint.is_dir() or not any(item.is_file() for item in checkpoint.rglob("*")):
        raise RuntimeError("INCOMPLETE: retained checkpoint tree is missing")
    files = sorted(item for item in checkpoint.rglob("*") if item.is_file())
    dcp = [item for item in files if item.suffix == ".distcp" or item.name == ".metadata"]
    if dcp:
        raise RuntimeError("INCOMPLETE: DCP/sharded checkpoint requires a separately reviewed adapter")
    payloads = [item for item in files if item.suffix in {".pt", ".pth", ".bin"}]
    if not payloads:
        raise RuntimeError("INCOMPLETE: no supported torch checkpoint payload found")
    if out.exists():
        raise RuntimeError(f"INVALID: refusing to overwrite inventory {out}")
    payload_dir = out.parent / f"{out.stem}.payloads"
    if payload_dir.exists():
        raise RuntimeError(f"INVALID: refusing to overwrite payload directory {payload_dir}")
    payload_dir.mkdir(parents=True)
    tensors = []
    try:
        for source in payloads:
            try:
                state = torch.load(source, map_location="cpu", weights_only=True)
            except Exception as exc:
                raise RuntimeError(f"INCOMPLETE: safe torch load failed for {source.name}: {exc}") from exc
            if not isinstance(state, dict):
                raise RuntimeError(f"INCOMPLETE: payload {source.name} is not a tensor mapping")
            for key, value in sorted(_flatten(state).items()):
                if not isinstance(value, torch.Tensor):
                    continue
                dtype, representation = _dtype_spec(value)
                token = hashlib.sha256(f"{source.relative_to(checkpoint)}::{key}".encode()).hexdigest()[:20]
                target = payload_dir / f"{token}.npy"
                _npy(target, value, representation)
                tensors.append(
                    {
                        "name": f"{source.relative_to(checkpoint)}::{key}",
                        "shape": list(value.shape),
                        "dtype": dtype,
                        "npy": str(target.relative_to(out.parent)),
                        "payload_dtype": representation,
                        "payload_sha256": sha256_file(target),
                    }
                )
        if not tensors:
            raise RuntimeError("INCOMPLETE: supported checkpoint has no tensor leaves")
        payload = {
            "schema_version": 1,
            "arm_name": arm_name,
            "product_sha": identity["PRODUCT_SHA"],
            "protocol_sha256": identity["PROTOCOL_SHA256"],
            "recipe_sha256": identity["RECIPE_SHA256"],
            "dataset_sha256": identity["DATASET_SHA256"],
            "env_fingerprint_sha256": identity["ENV_FINGERPRINT_SHA256"],
            "comparator_sha256": identity["COMPARATOR_SHA256"],
            "lock_sha256": identity["LOCK_SHA256"],
            "checkpoint_tree_sha256": tree_hash(checkpoint),
            "checkpoint_root": str(checkpoint.resolve()),
            "tensors": tensors,
            "self_sha256": None,
        }
        payload["self_sha256"] = self_hash(payload)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return payload
    except Exception:
        # Keep partial payloads for forensic inspection, but never construct a
        # valid inventory pointing at them.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--arm-name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        from c2_parameter_campaign_927c5de import load_lock

        lock = load_lock(args.lock)
        if lock["STAGE"] != "CALIBRATION" or args.arm_name not in lock["ARM_ORDER"]:
            raise RuntimeError("INVALID: inventory export requires a locked calibration arm")
        export_inventory(
            args.checkpoint, args.out, identity={**lock, "LOCK_SHA256": sha256_file(args.lock)}, arm_name=args.arm_name
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1 if str(exc).startswith("INCOMPLETE:") else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
