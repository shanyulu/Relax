# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Unit checks for exact semantic comparison of checkpoint metadata values."""

from argparse import Namespace
from enum import Enum

import pytest
from audit_non_tensor_checkpoint_state_927c5de import (
    AuditError,
    _namespace_difference_classes,
    differing_paths,
    digest_normalised,
    normalise_value,
)


class Role(str, Enum):
    TRAIN = "train"


def test_namespace_normalisation_compares_actual_nested_values():
    left = normalise_value(Namespace(step=48, nested={"enabled": True, "lr": 1e-5}))
    same = normalise_value(Namespace(step=48, nested={"enabled": True, "lr": 1e-5}))
    changed = normalise_value(Namespace(step=49, nested={"enabled": True, "lr": 1e-5}))

    assert left == same
    assert left != changed
    assert digest_normalised(left) == digest_normalised(same)
    assert differing_paths(left, changed) == ["$.fields.step.value"]


def test_bool_and_integer_remain_distinct_checkpoint_values():
    assert normalise_value(True) != normalise_value(1)


def test_string_enum_preserves_enum_type_and_member():
    assert normalise_value(Role.TRAIN) == {
        "type": f"{Role.__module__}.Role",
        "name": "TRAIN",
        "value": {"type": "str", "value": "train"},
    }


def test_torch_dtype_has_a_stable_semantic_name():
    torch = pytest.importorskip("torch")
    assert normalise_value(torch.float32) == {"type": "torch.dtype", "value": "float32"}


def test_omegaconf_is_compared_as_unresolved_configuration_values():
    omega = pytest.importorskip("omegaconf")
    value = omega.OmegaConf.create({"optimizer": {"lr": 1e-5}, "enabled": True})
    result = normalise_value(value)
    assert result["fields"]["optimizer"]["fields"]["lr"] == {"type": "float", "hex": (1e-5).hex()}


def test_namespace_difference_classification_separates_run_identity_from_config():
    baseline = {
        "type": "argparse.Namespace",
        "fields": {
            "save": {"type": "str", "value": "/run/a"},
            "tq_config": {
                "type": "builtins.dict",
                "fields": {"controller": {"fields": {"zmq_info": {"fields": {"id": {"value": "a"}}}}}},
            },
        },
    }
    changed = {
        "type": "argparse.Namespace",
        "fields": {
            "save": {"type": "str", "value": "/run/b"},
            "tq_config": {
                "type": "builtins.dict",
                "fields": {"controller": {"fields": {"zmq_info": {"fields": {"id": {"value": "b"}}}}}},
            },
        },
    }

    categories = _namespace_difference_classes(
        {"P-M1-off": baseline, "P-M1-on": changed, "P-M2-on": changed, "P-M2-off": changed}
    )
    assert categories["run_output_identity"] == ["save.value"]
    assert categories["runtime_endpoint"] == ["tq_config.fields.controller.fields.zmq_info.fields.id.value"]
    assert "other_configuration" not in categories


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_checkpoint_scalar_is_rejected(value):
    with pytest.raises(AuditError, match="non-finite"):
        normalise_value(value)


def test_unknown_object_is_rejected_instead_of_stringified():
    class Opaque:
        pass

    with pytest.raises(AuditError, match="unsupported semantic value type"):
        normalise_value(Opaque())
