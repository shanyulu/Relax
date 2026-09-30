# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Coverage audit rejects structural omissions; descriptive deltas never imply
acceptance."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from native_secondary_audit_927c5de import coverage, delta_series


def fixture():
    item = SimpleNamespace(
        size=[4],
        properties=SimpleNamespace(dtype="torch.bfloat16"),
        chunks=[SimpleNamespace(offsets=[0], sizes=[2]), SimpleNamespace(offsets=[2], sizes=[2])],
    )
    metadata = SimpleNamespace(state_dict_metadata={"model.weight": item, "extra": SimpleNamespace()})
    inventory = {"tensors": [{"name": "x::model.weight", "shape": [4], "dtype": "bfloat16"}]}
    adapter = {
        "sanitized_tensor_count": 1,
        "sanitized_tensor_keys": 1,
        "dropped_non_tensor_count": 1,
        "dropped_non_tensor_leaves": [{"key": "extra[0].step"}],
    }
    return metadata, inventory, adapter


def test_complete_metadata_coverage():
    result = coverage(*fixture())
    assert result["model_elements"] == 4
    assert result["tensor_storage_count"] == 1


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "shape", "dtype", "overlap", "hole", "bounds", "unaccounted"]
)
def test_rejects_coverage_gaps(change):
    metadata, inventory, adapter = deepcopy(fixture())
    if change == "missing":
        inventory["tensors"].clear()
    elif change == "duplicate":
        inventory["tensors"] *= 2
    elif change in ("shape", "dtype"):
        inventory["tensors"][0][change] = [3] if change == "shape" else "float32"
    elif change == "unaccounted":
        metadata.state_dict_metadata["unaccounted"] = SimpleNamespace()
    else:
        chunk = metadata.state_dict_metadata["model.weight"].chunks[1]
        chunk.offsets = [1 if change == "overlap" else 3]
        chunk.sizes = [1] if change == "hole" else [2]
    with pytest.raises(ValueError):
        coverage(metadata, inventory, adapter)


def test_empty_placeholder_is_not_a_model_element():
    metadata, inventory, adapter = fixture()
    metadata.state_dict_metadata["te_extra"] = SimpleNamespace()
    inventory["tensors"].append({"name": "x::te_extra[0]", "shape": [0], "dtype": "uint8"})
    adapter["sanitized_tensor_count"] = adapter["sanitized_tensor_keys"] = 2
    result = coverage(metadata, inventory, adapter)
    assert result["empty_placeholder_count"] == 1
    assert result["model_elements"] == 4


def test_delta_describes_nonzero_values_without_pass_status():
    result = delta_series([1.0, 3.0], [2.0, 2.0])
    assert result["max_abs_delta"] == 1.0
    assert result["mean_signed_delta"] == 0.0
    assert "status" not in result


def test_numeric_equality_is_not_bit_equality():
    assert delta_series([0.0], [-0.0])["numerically_equal"] is True


@pytest.mark.parametrize("off,on", [([], []), ([1.0], [1.0, 2.0]), ([float("nan")], [1.0]), ([1.0], [float("inf")])])
def test_bad_series_rejected(off, on):
    with pytest.raises(ValueError):
        delta_series(off, on)
