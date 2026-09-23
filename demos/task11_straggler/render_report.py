# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Render the measured Task 11 demo output as a compact evidence sheet."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--compare", type=Path, help="second run with the same source and configuration")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    comparison = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    if comparison and (data["config"] != comparison["config"] or data["source_sha256"] != comparison["source_sha256"]):
        parser.error("comparison requires identical configuration and measured source files")
    ink, muted, blue, orange, pale = "#152D4A", "#68788D", "#1869A8", "#D88A28", "#E7EEF4"
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
    )
    figure, axes = plt.subplots(2, 2, figsize=(14, 9))
    figure.subplots_adjust(left=0.065, right=0.97, bottom=0.12, top=0.83, hspace=0.48, wspace=0.23)
    figure.patch.set_facecolor("white")
    figure.suptitle(
        "Relax Straggler  /  mechanism evidence", x=0.065, y=0.965, ha="left", fontsize=20, weight="bold", color=ink
    )
    figure.text(
        0.065, 0.919, "Local GPUs · async Event collection · paired timing · workload-aware comparison", color=muted
    )

    trials = data["paired_trials"]
    null_values = [row["difference_pct"] for row in data.get("null_trials", [])]
    x = np.arange(len(trials))
    values = [row["overhead_pct"] for row in trials]
    axis = axes[0, 0]
    if comparison:
        other_values = [row["overhead_pct"] for row in comparison["paired_trials"]]
        other_null_values = [row["difference_pct"] for row in comparison.get("null_trials", [])]
        axis.bar(x - 0.18, values, width=0.36, color=blue, label="Run 1")
        axis.bar(x + 0.18, other_values, width=0.36, color=orange, label="Run 2")
        if null_values and other_null_values:
            axis.scatter(
                x - 0.18, null_values, marker="D", facecolors="white", edgecolors=ink,
                s=32, label="Off / off control", zorder=4,
            )
            axis.scatter(
                x + 0.18, other_null_values, marker="D", facecolors="white", edgecolors=ink, s=32, zorder=4,
            )
        axis.legend(frameon=False, loc="upper left")
        plotted = values + other_values + null_values + other_null_values
        axis.set_ylim(min(-0.1, min(plotted) - 0.1), max(0.6, max(plotted) + 0.1))
    else:
        axis.bar(x, values, width=0.55, color=[blue if v < 0.5 else orange for v in values])
        if null_values:
            axis.scatter(
                x, null_values, marker="D", facecolors="white", edgecolors=ink,
                s=32, label="Off / off control", zorder=4,
            )
            axis.legend(frameon=False, loc="upper left")
    axis.axhline(0.5, color="#BE4A44", linewidth=1.2, linestyle="--")
    axis.axhline(0, color=muted, linewidth=0.7)
    axis.set_title("A  Paired overhead and baseline noise", loc="left", weight="bold", color=ink)
    ci = data["bootstrap_mean_95pct_interval_pct"]
    label = f"AB / BA trial  ·  Run 1 median {statistics.median(values):+.3f}%"
    if comparison:
        label += f"  ·  Run 2 median {statistics.median(other_values):+.3f}%"
    label += f"\nRun 1 mean 95% [{ci[0]:+.3f}, {ci[1]:+.3f}]%"
    if comparison:
        other_ci = comparison["bootstrap_mean_95pct_interval_pct"]
        label += f"  ·  Run 2 [{other_ci[0]:+.3f}, {other_ci[1]:+.3f}]%"
    axis.set_xlabel(label, fontsize=9)
    axis.set_ylabel("On / off - 1   (%)")
    axis.set_xticks(x, [str(i + 1) for i in x])
    axis.text(0.97, 0.5, "0.5% target", ha="right", va="bottom", color="#BE4A44", transform=axis.get_yaxis_transform())

    by_case: dict[tuple[str, int, str], dict[int, float]] = defaultdict(dict)
    for item in data["samples"]:
        for stage, duration in item["stages_ms"].items():
            by_case[(item["case"], item["step"], stage)][item["rank"]] = duration
    axis = axes[0, 1]
    sampled_steps = sorted(step for case, step, stage in by_case if case == "compute_slow" and stage == "forward")
    for rank, color in ((0, blue), (1, orange)):
        axis.plot(
            sampled_steps,
            [by_case[("compute_slow", step, "forward")][rank] for step in sampled_steps],
            marker="o",
            color=color,
            label=f"rank {rank}",
        )
    axis.set_title("B  Run 1: injected forward work", loc="left", weight="bold", color=ink)
    axis.set_xlabel("Logical step")
    axis.set_ylabel("GPU stream interval  (ms)")
    axis.legend(frameon=False)

    axis = axes[1, 0]
    cases = ("control", "compute_slow", "host_stall")
    positions = np.arange(len(cases))
    for rank, offset, color in ((0, -0.18, blue), (1, 0.18, orange)):
        medians = [
            statistics.median(
                item["stages_ms"]["collective_interval"]
                for item in data["samples"]
                if item["case"] == case and item["rank"] == rank
            )
            for case in cases
        ]
        axis.bar(positions + offset, medians, width=0.36, label=f"rank {rank}", color=color)
    axis.set_xticks(positions, ["Control", "Extra forward", "Host stall"])
    axis.set_title("C  Run 1: collective interval (includes waits)", loc="left", weight="bold", color=ink)
    axis.set_ylabel("Median GPU stream interval  (ms)")
    axis.legend(frameon=False)

    axis = axes[1, 1]
    axis.axis("off")
    telemetry = data["telemetry"]
    received = telemetry.get("received", telemetry["reported"])
    coverage = received / telemetry["planned"] if telemetry["planned"] else 0
    dropped = sum(
        telemetry.get(key, 0)
        for key in ("dropped_pool", "dropped_queue", "dropped_sink", "dropped_collector", "dropped_shutdown")
    )
    payload_size = (
        f"{telemetry['json_payload_bytes'] / telemetry['reported']:.0f} B" if telemetry["reported"] else "n/a"
    )
    card = [
        (f"{coverage:.1%}", "samples received"),
        (f"{dropped}", "dropped by probe / transport"),
        (payload_size, "JSON payload per report"),
        (f"{telemetry['max_report_lag_ms']:.0f} ms", "worst step-open to readout"),
    ]
    axis.set_title("D  Run 1: data quality", loc="left", weight="bold", color=ink)
    for index, (number, label) in enumerate(card):
        y = 0.85 - 0.21 * index
        axis.text(
            0.04, y, number, fontsize=20, weight="bold", color=blue if index != 1 else orange, transform=axis.transAxes
        )
        axis.text(0.48, y + 0.015, label, color=ink, transform=axis.transAxes)
        if index < 3:
            axis.plot([0.04, 0.94], [y - 0.06, y - 0.06], color=pale, transform=axis.transAxes)

    figure.text(
        0.065,
        0.045,
        "Standalone synthetic training loop. Event intervals include possible waits; no hardware-fault verdict. "
        "Not a Relax recipe acceptance run.",
        color=muted,
        fontsize=9,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180, facecolor="white", bbox_inches="tight")
    plt.close(figure)
    print(args.output)


if __name__ == "__main__":
    main()
