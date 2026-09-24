# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Plot the autoscaler full-cycle timeline from autoscaler_run_20260924_v3 raw data.

Inputs : timeline.json (1 Hz capacity snapshots), events.json (phase boundaries)
Output : timeline-chart.png (committed next to the raw data it renders)
"""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
timeline = json.load(open(os.path.join(HERE, "timeline.json")))
events = json.load(open(os.path.join(HERE, "events.json")))

T0 = 74.6  # load_started


def t(ev_name):
    for e in events:
        if e["event"] == ev_name:
            return e["t"] - T0
    return None


t_low_done = t("phase_low_done")
t_high_done = t("phase_high_result")
t_steady_done = t("phase_low_prime_result")
t_load_stop = t("load_stopped")

# capacity series
ts, cap = [], []
served_init, served_elastic = [], []
for row in timeline:
    ts.append(row["t"] - T0)
    cap.append(row["current"])
    per = {p: s for _, p, s in row["engines"]}
    served_init.append(per.get(16000, None))
    served_elastic.append(per.get(16001, None))

# elastic engine served count: events.json is authoritative (timeline snapshots at 1 Hz can miss the last request)
elastic_total = next(e["elastic_served"] for e in events if e["event"] == "phase_steady_done")

C_BLUE, C_ORANGE, C_GREEN, C_RED, C_GRAY = "#1f5fb4", "#e07b28", "#1a8f5c", "#c23a3a", "#8a8f98"

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(10.4, 5.9), sharex=True, gridspec_kw={"height_ratios": [1.15, 1], "hspace": 0.12}
)

# ---- panel 1: capacity ----
phases = [
    (0, t_low_done, "LOW", "#eef3fb"),
    (t_low_done, t_high_done, "HIGH (saturated)", "#fdeee0"),
    (t_high_done, t_steady_done, "STEADY", "#e9f5ef"),
    (t_steady_done, t_load_stop, "LOW'", "#eef3fb"),
]
for x0, x1, name, color in phases:
    ax1.axvspan(x0, x1, color=color, zorder=0)
    ax2.axvspan(x0, x1, color=color, zorder=0)
    ax1.text((x0 + x1) / 2, 2.82, name, ha="center", va="top", fontsize=8.5, color="#444a54")

ax1.step(ts, cap, where="post", color=C_BLUE, lw=2.2, zorder=3)
ax1.fill_between(ts, cap, step="post", color=C_BLUE, alpha=0.10, zorder=2)
ax1.set_ylim(0.6, 3.0)
ax1.set_yticks([1, 2])
ax1.set_ylabel("GenRM engine count (current)", fontsize=9.5)
ax1.tick_params(labelsize=9)

t_so, t_si = t_high_done, t_steady_done
ax1.annotate(
    "auto scale-out 1\u21922\ntrigger: token_usage_high",
    xy=(t_so, 2), xytext=(t_so - 36, 2.38),
    fontsize=8.5, color=C_GREEN, ha="center",
    arrowprops=dict(arrowstyle="-|>", color=C_GREEN, lw=1.2),
)
ax1.annotate(
    "auto scale-in 2\u21921\ntriggers: token_usage_low + no_queue\n+ throughput_stable",
    xy=(t_si, 1), xytext=(t_si + 16, 2.0),
    fontsize=8.5, color=C_RED, ha="center",
    arrowprops=dict(arrowstyle="-|>", color=C_RED, lw=1.2),
)
ax1.text(2, 1.13, "initial engine only \u2014 no false scale-out under LOW", fontsize=8, color="#444a54", va="bottom")
ax1.set_title(
    "GenRM autoscaler full cycle on 4\u00d7RTX 4090 (Qwen3-0.6B judge): auto 1\u21922\u21921, 3,202 requests, 0 failures",
    fontsize=10.5, pad=8,
)

# ---- panel 2: per-engine cumulative served ----
ax2.plot(ts, served_init, color=C_BLUE, lw=1.9, label="initial engine (port 16000)")
el_ts = [x for x, s in zip(ts, served_elastic) if s is not None]
el_s = [s for s in served_elastic if s is not None]
ax2.plot(el_ts, el_s, color=C_ORANGE, lw=1.9, label=f"elastic engine (port 16001, served {elastic_total})")
ax2.set_ylabel("Cumulative requests served", fontsize=9.5)
ax2.set_xlabel(f"Elapsed time since load start (s) \u2014 1 Hz snapshots, {len(ts)} rows", fontsize=9.5)
ax2.set_xlim(-2, t_load_stop + 3)
ax2.legend(loc="upper left", fontsize=8.5, framealpha=0.9)
ax2.tick_params(labelsize=9)
ax2.grid(axis="y", color="#d8dce2", lw=0.6, alpha=0.7)

# elastic-engine annotation on its curve end
ax2.annotate(
    f"elastic engine drained\n(516 served, DRAINING\u2192COMPLETED)",
    xy=(el_ts[-1], el_s[-1]), xytext=(el_ts[-1] + 9, el_s[-1] - 260),
    fontsize=8, color=C_ORANGE,
    arrowprops=dict(arrowstyle="-|>", color=C_ORANGE, lw=1.0),
)

for ax in (ax1, ax2):
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

fig.savefig(os.path.join(HERE, "timeline-chart.png"), dpi=200, bbox_inches="tight", facecolor="white")
print("written", os.path.join(HERE, "timeline-chart.png"))
print("phases:", [round(p, 1) for p in (t_low_done, t_high_done, t_steady_done, t_load_stop)])
print("elastic_total:", elastic_total, "timeline rows:", len(ts))
