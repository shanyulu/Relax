#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Render per-pair overhead + bootstrap CI diagram from a finished campaign.

Inputs:
  - campaign root dir (arm subdirs with manifest.json + job.log)
  - campaign driver log (lines like "[campaign] S1-off: exit=0 valid=True ... wall=308.122")

Output: markdown fragment with
  - per-pair whole-run wall delta (ON - OFF, signed) and overhead %
  - mean overhead + bootstrap 95% CI over pairs (resampling pairs, 10k draws)
  - mermaid xychart bar chart of per-pair overhead %
Read-only with respect to campaign data.
"""

import ast
import json
import random
import re
import sys
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PERF_RE = re.compile(r"perf (\d+): (\{.*\})\s*$")
WALL_RE = re.compile(r"\[campaign\] (S\d+)-(on|off): exit=(\d+) valid=(\w+).*?wall=([0-9.]+)")


def arm_tokens_and_steps(log: Path):
    steps = {}
    if not log.exists():
        return steps
    with log.open("r", errors="replace") as fh:
        for raw in fh:
            m = PERF_RE.search(ANSI_RE.sub("", raw))
            if m:
                try:
                    steps[int(m.group(1))] = ast.literal_eval(m.group(2))
                except (ValueError, SyntaxError):
                    pass
    return steps


def main() -> int:
    root = Path(sys.argv[1])
    driver_log = Path(sys.argv[2])
    walls = {}
    for raw in driver_log.read_text(errors="replace").splitlines():
        m = WALL_RE.search(raw)
        if m and m.group(3) == "0" and m.group(4) == "True":
            walls[f"{m.group(1)}-{m.group(2)}"] = float(m.group(5))

    sessions = {}
    for key, wall in walls.items():
        session, arm = key.rsplit("-", 1)
        perf = arm_tokens_and_steps(root / key / "job.log")
        train_total = sum(v.get("perf/train_time", 0.0) for v in perf.values())
        tokens_total = sum(v.get("perf/actor_train_tokens", 0) or 0 for v in perf.values())
        manifest = {}
        mf = root / key / "manifest.json"
        if mf.exists():
            manifest = json.loads(mf.read_text())
        sessions.setdefault(session, {})[arm] = {
            "wall": wall,
            "train_time_total": train_total,
            "tokens_total": tokens_total,
            "steps": len(perf),
            "order": manifest.get("order"),
            "recipe": manifest.get("recipe"),
        }

    pairs = []
    for session in sorted(sessions):
        s = sessions[session]
        if "off" not in s or "on" not in s:
            continue
        off, on = s["off"], s["on"]
        delta = on["wall"] - off["wall"]
        pairs.append(
            {
                "session": session,
                "order": off.get("order"),
                "wall_off": off["wall"],
                "wall_on": on["wall"],
                "delta_s": delta,
                "overhead_pct": 100.0 * delta / off["wall"],
                "tokens_equal": off["tokens_total"] == on["tokens_total"],
                "steps_equal": off["steps"] == on["steps"],
            }
        )

    if not pairs:
        print("no complete valid pairs yet")
        return 1

    overheads = [p["overhead_pct"] for p in pairs]
    mean = sum(overheads) / len(overheads)
    rng = random.Random(20260927)
    n = len(pairs)
    draws = []
    for _ in range(10000):
        sample = [overheads[rng.randrange(n)] for _ in range(n)]
        draws.append(sum(sample) / n)
    draws.sort()
    lo, hi = draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))]

    lines = []
    lines.append("## Task 11 — observer overhead per pair (whole-run wall, AB/BA balanced)\n")
    lines.append("| pair | order | OFF wall (s) | ON wall (s) | Δ (s) | overhead % | tokens equal | steps equal |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in pairs:
        lines.append(
            f"| {p['session']} | {p['order']} | {p['wall_off']:.1f} | {p['wall_on']:.1f} | "
            f"{p['delta_s']:+.1f} | {p['overhead_pct']:+.2f}% | {p['tokens_equal']} | {p['steps_equal']} |"
        )
    lines.append(
        f"\nMean overhead **{mean:+.2f}%**, bootstrap 95% CI **[{lo:+.2f}%, {hi:+.2f}%]** "
        f"({n} pairs, 10k pair-level resamples, seed 20260927)."
    )
    lines.append("\n```mermaid\nxychart-beta\n")
    lines.append('    title "Per-pair observer overhead (% of whole-run wall)"')
    lines.append("    bar [")
    lines.append(", ".join(f"{p['overhead_pct']:.2f}" for p in pairs))
    lines.append("    ]")
    lines.append("```\n")
    out = root / "pair_overhead_diagram.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines[-6:]))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
