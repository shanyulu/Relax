#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Render frozen parameter deltas without treating placeholders as samples."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path

from c2_parameter_verdict_927c5de import canonical_sha256


def metric_text(delta: float, tolerance: float) -> str:
    if not math.isfinite(delta) or not math.isfinite(tolerance) or delta < 0 or tolerance < 0:
        raise ValueError("non-finite or negative delta/tolerance")
    if tolerance == 0:
        return "0 / 0 · 数值相等" if delta == 0 else "超界 · 零容差"
    return f"{delta / tolerance:.3f} × 容差"


def short_name(name: str) -> str:
    label = name.removeprefix("converted_tensors.pt::")
    if label.startswith("optimizer.distributed."):
        return "optimizer · " + label.rsplit(".", 1)[-1]
    return label


def render(result: dict, calibration: dict) -> str:
    for value in (result, calibration):
        if value.get("self_sha256") != canonical_sha256(value):
            raise ValueError("input self hash mismatch")
    pairs = result.get("pairs", [])
    if [pair.get("pair_id") for pair in pairs] != ["P-M1", "P-M2"]:
        raise ValueError("expected two ordered pairs")
    names = sorted(calibration["tensor_tolerances"])
    if not names:
        raise ValueError("empty floating tolerance table")
    for pair in pairs:
        if not set(names).issubset(pair["tensors"]):
            raise ValueError("missing floating tensor result")
    height = 198 + 38 * len(names)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{height}" viewBox="0 0 960 {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<g font-family="sans-serif" fill="#182b43">',
        '<text x="28" y="36" font-size="21" font-weight="600">最终 checkpoint：差值相对冻结包络</text>',
        f'<text x="28" y="62" font-size="13">{len(names)} 个浮点张量组 × 2 对；空占位项不计入此图</text>',
        '<text x="550" y="102" font-size="14">M1 · OFF → ON</text>',
        '<text x="760" y="102" font-size="14">M2 · ON → OFF</text>',
    ]
    for row, name in enumerate(names):
        y = 114 + row * 38
        lines.append(f'<text x="28" y="{y + 22}" font-size="12">{html.escape(short_name(name))}</text>')
        for column, pair in enumerate(pairs):
            item = pair["tensors"][name]
            tolerance = calibration["tensor_tolerances"][name]
            if item.get("tolerance") != tolerance:
                raise ValueError("displayed tolerance differs from calibration")
            delta = item["max_abs_delta"]
            text = metric_text(delta, tolerance)
            within = delta <= tolerance
            if item["state"] != ("PASS" if within else "NOT_PASS"):
                raise ValueError("displayed state differs from numeric result")
            x = 534 + column * 208
            fill = "#e4f2eb" if within else "#f9e2e5"
            lines.append(f'<rect x="{x}" y="{y}" width="192" height="30" rx="4" fill="{fill}"/>')
            lines.append(f'<text x="{x + 12}" y="{y + 20}" font-size="13">{html.escape(text)}</text>')
    footer = 136 + 38 * len(names)
    lines.extend(
        [
            f'<text x="28" y="{footer}" font-size="12">数值为 max-abs-delta / 冻结容差；≤ 1 通过，不是置信区间。</text>',
            f'<text x="28" y="{footer + 23}" font-size="11">结果 self SHA：{result["self_sha256"]}</text>',
            "</g></svg>\n",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    calibration = json.loads(args.calibration.read_text())
    if result["calibration_sha256"] != hashlib.sha256(args.calibration.read_bytes()).hexdigest():
        raise ValueError("result/calibration binding mismatch")
    with args.out.open("x") as target:
        target.write(render(result, calibration))


if __name__ == "__main__":
    main()
