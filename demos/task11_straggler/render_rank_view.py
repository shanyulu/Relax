# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Render a rank-by-stage operator view from measured demo samples."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


CASES = ("control", "compute_slow", "load_skew", "host_stall")
STAGES = ("forward", "backward", "collective_interval", "optimizer")
CASE_LABELS = {
    "control": "Control",
    "compute_slow": "Extra forward",
    "load_skew": "Unequal workload",
    "host_stall": "Host stall",
}


def build_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for sample in data["samples"]:
        if sample["case"] in CASES:
            grouped[(sample["case"], sample["rank"])].append(sample)
    alerts = defaultdict(list)
    for alert in data["diagnosis"]["alerts"]:
        alerts[(alert["case"], alert["rank"])].append(alert)
    uncertain_cases = {row["case"] for row in data["diagnosis"]["uncertain"]}
    planned_per_rank = math.ceil(data["config"]["injection_steps"] / data["config"]["interval"])
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for rank in range(data["environment"]["world_size"]):
            samples = grouped[(case, rank)]
            if not samples:
                rows.append({"case": case, "rank": rank, "coverage": f"0/{planned_per_rank}", "status": "unknown"})
                continue
            stages = {
                stage: statistics.median(
                    sample["stages_ms"][stage] for sample in samples if stage in sample["stages_ms"]
                )
                for stage in STAGES
                if any(stage in sample["stages_ms"] for sample in samples)
            }
            findings = alerts[(case, rank)]
            complete = len(samples) == planned_per_rank and all(
                stage in sample["stages_ms"] for sample in samples for stage in STAGES
            )
            if findings:
                status = ", ".join(f"{alert['stage']} @ step {alert['step']}" for alert in findings)
                if not complete:
                    status += "; partial data"
            elif not complete:
                status = "insufficient data"
            elif case in uncertain_cases:
                status = "not comparable"
            else:
                status = "no alert"
            rows.append(
                {
                    "case": case,
                    "rank": rank,
                    "workload": samples[0]["workload"],
                    "coverage": f"{len(samples)}/{planned_per_rank}",
                    "stages": stages,
                    "status": status,
                }
            )
    return rows


def markdown(data: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    telemetry = data["telemetry"]
    received = telemetry.get("received", len(data["samples"]))
    lines = [
        "# Rank × stage view (measured standalone demo)",
        "",
        f"Samples received: {received}/{telemetry['planned']}; "
        f"collector errors / transport drops: {telemetry.get('collector_error', 'not recorded')}/"
        f"{telemetry.get('dropped_sink', 'not recorded')}.",
        "Durations are per-rank medians in milliseconds; collective intervals can include peer wait.",
        "",
        "| Case | Rank | Workload | Forward | Backward | Collective interval | Optimizer | Samples | Finding |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        stages = row.get("stages", {})
        durations = [f"{stages[stage]:.3f}" if stage in stages else "—" for stage in STAGES]
        lines.append(
            f"| {CASE_LABELS[row['case']]} | {row['rank']} | {row.get('workload', '—')} | "
            + " | ".join(durations)
            + f" | {row['coverage']} | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "The extra-forward case identifies a measured rank/stage slowdown; it does not identify a hardware fault. "
            "The unequal-workload case is excluded from peer comparison. No MetricsService integration or "
            "end-to-end alert latency is claimed here.",
            "",
        ]
    )
    return "\n".join(lines)


def draw(rows: list[dict[str, Any]], data: dict[str, Any], output: Path) -> None:
    import matplotlib.pyplot as plt

    ink, blue, orange, muted = "#152D4A", "#1B639C", "#C97724", "#64748B"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    figure = plt.figure(figsize=(16, 7.4), facecolor="white")
    figure.text(0.045, 0.935, "Rank × stage / observed samples", fontsize=24, weight="bold", color=ink)
    figure.text(
        0.045, 0.878,
        f"Median GPU stream interval (ms) · one local {data['environment']['world_size']}-GPU run · "
        "no platform integration",
        fontsize=11, color=muted,
    )
    columns = ["Scenario", "Rank", "Work", "Forward", "Backward", "Collective", "Optimizer", "Samples", "Finding"]
    cells = []
    for row in rows:
        stages = row.get("stages", {})
        cells.append(
            [CASE_LABELS[row["case"]], str(row["rank"]), str(row.get("workload", "—"))]
            + [f"{stages[stage]:.3f}" if stage in stages else "—" for stage in STAGES]
            + [row["coverage"], row["status"]]
        )
    axis = figure.add_axes([0.04, 0.22, 0.92, 0.58])
    axis.axis("off")
    table = axis.table(
        cellText=cells, colLabels=columns, cellLoc="center", loc="center",
        colWidths=[0.15, 0.055, 0.07, 0.09, 0.09, 0.10, 0.09, 0.075, 0.28],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2.65)
    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_edgecolor("#DCE5ED")
        cell.set_linewidth(0.7)
        if row_index == 0:
            cell.set_facecolor(ink)
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        else:
            row = rows[row_index - 1]
            has_alert = "@ step" in row["status"]
            cell.set_facecolor("#FFF1E4" if has_alert else ("#F1F5F9" if row_index % 2 == 0 else "white"))
            cell.get_text().set_color(orange if has_alert else ink)
            if col_index in (0, 8):
                cell.get_text().set_ha("left")
    telemetry = data["telemetry"]
    received = telemetry.get("received", len(data["samples"]))
    figure.text(0.045, 0.13, f"{received}/{telemetry['planned']}", fontsize=18, color=blue, weight="bold")
    figure.text(0.155, 0.135, "samples received", fontsize=10, color=muted)
    figure.text(0.41, 0.13, str(telemetry.get("collector_error", "n/a")), fontsize=18, color=blue, weight="bold")
    figure.text(0.438, 0.135, "collector errors", fontsize=10, color=muted)
    figure.text(0.7, 0.13, str(telemetry.get("dropped_sink", "n/a")), fontsize=18, color=blue, weight="bold")
    figure.text(0.728, 0.135, "transport drops", fontsize=10, color=muted)
    compute_alerts = [alert for alert in data["diagnosis"]["alerts"] if alert["case"] == "compute_slow"]
    finding = (
        f"Extra forward: rank {compute_alerts[0]['rank']} detected at logical step {compute_alerts[0]['step']}. "
        if compute_alerts else "Extra forward: no persistent rank alert. "
    )
    figure.text(
        0.045, 0.055,
        finding + "Workload mismatch is excluded; long collective time is not a link verdict.",
        fontsize=10, color=muted,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180, facecolor="white", bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--image", type=Path)
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    rows = build_rows(data)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown(data, rows), encoding="utf-8")
    if args.image:
        draw(rows, data, args.image)


if __name__ == "__main__":
    main()
