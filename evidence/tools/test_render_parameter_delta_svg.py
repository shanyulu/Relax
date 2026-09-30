from __future__ import annotations

import pathlib
import sys
import xml.etree.ElementTree as ET

import pytest


sys.path.insert(0, str(pathlib.Path(__file__).parent))
import render_parameter_delta_svg as plot  # noqa: E402


def signed(value):
    value["self_sha256"] = plot.canonical_sha256(value)
    return value


@pytest.mark.parametrize("delta,tol,text", [(0, 0, "数值相等"), (1, 0, "超界"), (0.5, 1, "0.500")])
def test_metric_zero_tolerance_is_not_divided(delta, tol, text):
    assert text in plot.metric_text(delta, tol)


@pytest.mark.parametrize("delta,tol", [(float("nan"), 1), (1, float("inf")), (-1, 1), (1, -1)])
def test_metric_rejects_invalid_numbers(delta, tol):
    with pytest.raises(ValueError):
        plot.metric_text(delta, tol)


def test_svg_escapes_names_and_checks_frozen_tolerance():
    key = "model<&>"
    calibration = signed({"tensor_tolerances": {key: 1}, "self_sha256": None})
    item = {"tolerance": 1, "max_abs_delta": 0.5, "state": "PASS"}
    result = signed({"pairs": [{"pair_id": name, "tensors": {key: item.copy()}} for name in ("P-M1", "P-M2")]})
    ET.fromstring(plot.render(result, calibration))
    result["pairs"][0]["tensors"][key]["tolerance"] = 2
    signed(result)
    with pytest.raises(ValueError, match="calibration"):
        plot.render(result, calibration)
