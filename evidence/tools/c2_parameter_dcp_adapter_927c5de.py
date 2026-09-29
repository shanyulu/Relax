#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Convert a retained Megatron DCP checkpoint into an ordinary torch tree.

The 927c5de layout probe established that this recipe's SAVE=1 output is a
DCP sharded checkpoint (``__<rank>_0.distcp`` + ``.metadata``), for which the
inventory exporter correctly refuses to guess. This adapter is the separately
reviewed bridge required by ``C2_EXECUTION_CHECKLIST_927C5DE.md`` section 2:
it converts one iteration directory with torch's own offline utility
``torch.distributed.checkpoint.format_utils.dcp_to_torch_save`` (CPU, no
process group), records full provenance
(source tree hash, converted payload hash, torch build), and never overwrites
existing output. The converted tree is what
``c2_parameter_inventory_927c5de.py`` then exports.

The converter and the intermediate load deserialize checkpoint byte payloads;
only use this tool on checkpoints produced by this campaign's own training
jobs. Status: PROPOSED for review — no formal parameter lock may reference this
adapter until the review lands (see STORAGE_AND_ADAPTER_ESCALATION_927C5DE.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def find_iteration(checkpoint: Path) -> Path:
    """Resolve the retained iteration directory of a Megatron DCP
    checkpoint."""
    if (checkpoint / ".metadata").is_file():
        return checkpoint
    marker = checkpoint / "latest_checkpointed_iteration.txt"
    if marker.is_file():
        iteration = marker.read_text().strip()
        candidate = checkpoint / f"iter_{int(iteration):08d}"
        if (candidate / ".metadata").is_file():
            return candidate
    candidates = sorted(path for path in checkpoint.glob("iter_*") if (path / ".metadata").is_file())
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError("INCOMPLETE: no single DCP iteration directory found")


def flatten_leaves(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten checkpoint leaves while rejecting ambiguous encoded paths."""
    result: dict[str, Any] = {}

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key in sorted(item, key=str):
                visit(item[key], f"{path}.{key}" if path else str(key))
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        else:
            if path in result:
                raise RuntimeError(f"INVALID: flattened checkpoint key collision: {path}")
            result[path] = item

    visit(value, prefix)
    return result


def convert(checkpoint: Path, out: Path, *, arm_name: str) -> dict[str, Any]:
    try:
        import torch
        from torch.distributed.checkpoint.format_utils import dcp_to_torch_save
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(f"INCOMPLETE: torch DCP utilities unavailable: {exc}") from exc

    iteration = find_iteration(checkpoint)
    shards = sorted(iteration.glob("*.distcp"))
    if not shards or not (iteration / ".metadata").is_file():
        raise RuntimeError("INCOMPLETE: not a DCP sharded layout")
    # Megatron's DCP byte payloads pickle-reference the megatron package
    # (optimizer state etc.), and torch's own converter loads those payloads
    # with weights_only=False. The adapter therefore REQUIRES the training
    # venv interpreter with the Megatron-LM source on PYTHONPATH — exactly the
    # environment the checkpoint was written in — so the checkpoint's own
    # classes resolve; a bare interpreter fails with ModuleNotFoundError
    # mid-conversion (found on the real probe fixture 2026-09-29). Only ever
    # run it on this campaign's own arm output.
    import importlib.util

    if importlib.util.find_spec("megatron.core") is None:
        raise RuntimeError(
            "INCOMPLETE: 'megatron.core' is not importable; run this adapter under the training venv "
            "with the Megatron-LM source on PYTHONPATH"
        )
    if out.exists():
        raise RuntimeError(f"INVALID: refusing to overwrite adapter output {out}")
    # The raw conversion lands in a SIBLING directory (<out>_raw/) because the
    # inventory exporter scans the whole checkpoint tree recursively for .pt
    # payloads; only the sanitized payload may sit under the inventory root.
    raw_dir = out.parent / f"{out.name}_raw"
    if raw_dir.exists():
        raise RuntimeError(f"INVALID: refusing to overwrite raw conversion {raw_dir}")
    out.mkdir(parents=True)
    raw_dir.mkdir(parents=True)
    payload = raw_dir / "converted.pt"
    source_tree = tree_hash(iteration)
    try:
        dcp_to_torch_save(iteration, payload)
    except BaseException:
        # A failed conversion must not leave a partial payload that blocks a
        # clean retry; the source tree is never touched.
        import shutil

        shutil.rmtree(out, ignore_errors=True)
        raise
    # Megatron checkpoints carry non-tensor leaves (omegaconf configs, param
    # groups) that a weights_only load must refuse. Parameter equivalence is
    # defined over tensors, so the adapter sanitises the converted payload to
    # plain {key: Tensor} — every dropped leaf is recorded by key and type in
    # the adapter record for review. The trusted-source load below reads this
    # campaign's own arm output only.
    state = torch.load(payload, map_location="cpu", weights_only=False)

    flat = flatten_leaves(state)
    tensors = {key: value for key, value in flat.items() if isinstance(value, torch.Tensor)}
    dropped = [
        {"key": key, "type": type(value).__module__ + "." + type(value).__qualname__}
        for key, value in flat.items()
        if not isinstance(value, torch.Tensor)
    ]
    final_payload = out / "converted_tensors.pt"
    torch.save(tensors, final_payload)
    record = {
        "schema": "C2_927C5DE_DCP_ADAPTER/v1",
        "status": "PROPOSED_PENDING_REVIEW",
        "arm_name": arm_name,
        "source_checkpoint_root": str(checkpoint.resolve()),
        "source_iteration_dir": str(iteration.resolve()),
        "source_tree_sha256": source_tree,
        "source_files": [{"path": str(path.relative_to(iteration)), "bytes": path.stat().st_size} for path in shards],
        "converter": "torch.distributed.checkpoint.format_utils.dcp_to_torch_save",
        "torch_version": torch.__version__,
        "raw_converted_path": str(payload.resolve()),
        "raw_converted_sha256": sha256_file(payload),
        "raw_converted_bytes": payload.stat().st_size,
        "sanitized_path": str(final_payload.resolve()),
        "sanitized_sha256": sha256_file(final_payload),
        "sanitized_bytes": final_payload.stat().st_size,
        "sanitized_tensor_count": len(tensors),
        "dropped_non_tensor_leaves": dropped,
        "dropped_non_tensor_count": len(dropped),
    }
    # The sanitized payload must load with the same safety posture as the
    # inventory exporter itself before anything downstream may read it.
    sanitized_state = torch.load(final_payload, map_location="cpu", weights_only=True)
    if not isinstance(sanitized_state, dict) or not sanitized_state:
        raise RuntimeError("INVALID: sanitized payload is not a non-empty tensor mapping")
    record["sanitized_tensor_keys"] = len(sanitized_state)
    (out / "ADAPTER_RECORD.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm-name", required=True)
    args = parser.parse_args()
    try:
        record = convert(args.checkpoint, args.out, arm_name=args.arm_name)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1 if str(exc).startswith("INCOMPLETE:") else 2
    print(
        json.dumps(
            {k: record[k] for k in ("arm_name", "source_tree_sha256", "sanitized_sha256", "sanitized_tensor_count")}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
