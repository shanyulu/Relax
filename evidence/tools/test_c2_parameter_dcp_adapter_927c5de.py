#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""DCP adapter round-trip tests (synthetic checkpoints, CPU-only)."""

from __future__ import annotations

import importlib.machinery
import json
import pathlib
import sys
import types

import pytest
import torch
from torch.distributed.checkpoint import FileSystemWriter
from torch.distributed.checkpoint.state_dict_saver import save as dcp_save


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c2_parameter_dcp_adapter_927c5de as adapter  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_megatron_core(monkeypatch):
    """The adapter refuses to run without megatron.core importable; the
    synthetic fixtures do not need the real package, only its presence."""
    for name in ("megatron", "megatron.core"):
        module = types.ModuleType(name)
        module.__spec__ = importlib.machinery.ModuleSpec(name, None)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)


def make_dcp(root: pathlib.Path) -> None:
    """Write a genuine no-dist DCP checkpoint: .metadata + __0_0.distcp."""
    state = {"weight": torch.arange(0, 12, dtype=torch.float32).reshape(3, 4), "step": torch.tensor([7])}
    dcp_save(state, storage_writer=FileSystemWriter(root), no_dist=True)
    assert (root / ".metadata").is_file()
    assert (root / "__0_0.distcp").is_file()


def test_synthetic_dcp_round_trips_through_the_adapter(tmp_path):
    source = tmp_path / "iter_00000007"
    make_dcp(source)
    out = tmp_path / "converted"
    record = adapter.convert(source.parent, out, arm_name="P-C1-off")
    assert record["status"] == "PROPOSED_PENDING_REVIEW"
    assert record["source_tree_sha256"] == adapter.tree_hash(source)
    assert record["sanitized_tensor_count"] == 2
    assert record["dropped_non_tensor_count"] == 0

    state = torch.load(out / "converted_tensors.pt", map_location="cpu", weights_only=True)
    assert (out.parent / f"{out.name}_raw" / "converted.pt").is_file()  # raw conversion retained as a sibling
    assert torch.equal(state["weight"], torch.arange(0, 12, dtype=torch.float32).reshape(3, 4))
    assert int(state["step"]) == 7
    # The adapter record must round-trip as JSON and pin the payload hash.
    reloaded = json.loads((out / "ADAPTER_RECORD.json").read_text())
    assert reloaded["sanitized_sha256"] == adapter.sha256_file(out / "converted_tensors.pt")


def test_adapter_finds_the_marked_iteration_and_refuses_overwrite(tmp_path):
    root = tmp_path / "ckpt"
    iteration = root / "iter_00000003"
    make_dcp(iteration)
    (root / "latest_checkpointed_iteration.txt").write_text("3\n")
    out = tmp_path / "converted"
    record = adapter.convert(root, out, arm_name="P-C2-off")
    assert record["source_iteration_dir"].endswith("iter_00000003")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        adapter.convert(root, out, arm_name="P-C2-off")


def test_adapter_finds_nested_recipe_checkpoint(tmp_path):
    root = tmp_path / "checkpoints"
    run = root / "sft" / "P-C1-off"
    iteration = run / "iter_0000003"
    make_dcp(iteration)
    (run / "latest_checkpointed_iteration.txt").write_text("3\n")
    assert adapter.find_iteration(root) == iteration


def test_adapter_rejects_multiple_nested_checkpoint_runs(tmp_path):
    root = tmp_path / "checkpoints"
    for name in ("P-C1-off", "P-C2-off"):
        run = root / "sft" / name
        make_dcp(run / "iter_0000003")
        (run / "latest_checkpointed_iteration.txt").write_text("3\n")
    with pytest.raises(RuntimeError, match="multiple DCP checkpoint markers"):
        adapter.find_iteration(root)


def test_non_dcp_layout_fails_closed(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    torch.save({"w": torch.zeros(2)}, plain / "model.pt")
    with pytest.raises(RuntimeError, match="INCOMPLETE"):
        adapter.convert(plain.parent, tmp_path / "out", arm_name="P-C3-off")


def test_flattened_tensor_keys_cannot_silently_collide():
    state = {"a": {"b": torch.tensor([1])}, "a.b": torch.tensor([2])}
    with pytest.raises(RuntimeError, match="flattened checkpoint key collision"):
        adapter.flatten_leaves(state)


def test_failed_dcp_conversion_cleans_only_its_own_partial_outputs(tmp_path, monkeypatch):
    source = tmp_path / "iter_00000007"
    make_dcp(source)
    out = tmp_path / "converted"

    def fail_after_partial_write(_source, target):
        target.write_bytes(b"partial")
        raise RuntimeError("synthetic conversion failure")

    monkeypatch.setattr("torch.distributed.checkpoint.format_utils.dcp_to_torch_save", fail_after_partial_write)
    with pytest.raises(RuntimeError, match="synthetic conversion failure"):
        adapter.convert(source, out, arm_name="P-C1-off")
    assert not out.exists()
    assert not (tmp_path / "converted_raw").exists()
    assert (source / ".metadata").is_file()


def test_failed_post_conversion_load_also_cleans_owned_outputs(tmp_path, monkeypatch):
    source = tmp_path / "iter_00000007"
    make_dcp(source)
    out = tmp_path / "converted"
    original = torch.load

    def fail_trusted_load(path, *args, **kwargs):
        if str(path).endswith("converted.pt"):
            raise RuntimeError("synthetic post-conversion failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(torch, "load", fail_trusted_load)
    with pytest.raises(RuntimeError, match="synthetic post-conversion failure"):
        adapter.convert(source, out, arm_name="P-C1-off")
    assert not out.exists()
    assert not (tmp_path / "converted_raw").exists()
    assert (source / ".metadata").is_file()
