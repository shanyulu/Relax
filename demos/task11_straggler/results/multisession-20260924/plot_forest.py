# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Forest plot for the 2026-09-24 multisession + A/A control experiment.

Panel (a): per-session paired off/on overhead (median + bootstrap mean 95% CI) vs the 0.5% bound.
           Two batches: sessions a-d (original multisession) and sessions A-D (A/A batch),
           each pooled separately to match the RFC-quoted numbers.
Panel (b): observer-bias controls -- A/A pairs (both arms instrumented) vs off/off null drift.

All values in the JSON files are already in percent units.

Inputs : session-{a..d}.json, aa-session-{A..D}.json
Output : multisession-forest.png
"""

import json
import os

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
N_BOOT = 10000


def boot_mean_ci(vals, seed=20260924):
    rng = np.random.default_rng(seed)
    vals = np.asarray(vals, dtype=float)
    means = rng.choice(vals, size=(N_BOOT, len(vals)), replace=True).mean(axis=1)
    return np.percentile(means, [2.5, 97.5])


def gpu_label(s):
    return ",".join(map(str, s["environment"]["gpu"]))


sessions = [(n, json.load(open(os.path.join(HERE, f"session-{n}.json")))) for n in "abcd"]
aa_sessions = [(n, json.load(open(os.path.join(HERE, f"aa-session-{n}.json")))) for n in "ABCD"]

# ---- pooled statistics (must match the RFC-quoted numbers) ----
onoff_ab = [tr["overhead_pct"] for _, s in sessions for tr in s["paired_trials"]]
onoff_AA = [tr["overhead_pct"] for _, s in aa_sessions for tr in s["paired_trials"]]
all_aa = [tr["difference_pct"] for _, s in aa_sessions for tr in s["aa_trials"]]
null_AA = [tr["difference_pct"] for _, s in aa_sessions for tr in s["null_trials"]]
null_ab = [tr["difference_pct"] for _, s in sessions for tr in s["null_trials"]]

for tag, vals in [("off/on a-d", onoff_ab), ("off/on A-D", onoff_AA), ("A/A A-D", all_aa), ("off/off A-D", null_AA), ("off/off a-d", null_ab)]:
    ci = boot_mean_ci(vals)
    print(f"{tag:12s} n={len(vals):2d}  median {np.median(vals):+.4f}%  boot-mean 95% CI [{ci[0]:+.4f}%, {ci[1]:+.4f}%]  "
          f"range [{min(vals):+.3f}%, {max(vals):+.3f}%]")

C_BLUE, C_TEAL, C_ORANGE, C_RED, C_GRAY = "#1f5fb4", "#128a8a", "#e07b28", "#c23a3a", "#9aa0a8"

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 5.0), gridspec_kw={"wspace": 0.30})

# ---- panel (a): off/on overhead forest ----
rows = []
for n, s in sessions:
    vals = [tr["overhead_pct"] for tr in s["paired_trials"]]
    rows.append((f"session {n} (GPU {gpu_label(s)})", np.median(vals), boot_mean_ci(vals), C_BLUE, 5.5))
for n, s in aa_sessions:
    vals = [tr["overhead_pct"] for tr in s["paired_trials"]]
    rows.append((f"session {n}, A/A batch (GPU {gpu_label(s)})", np.median(vals), boot_mean_ci(vals), C_TEAL, 5.5))
ci_ab, ci_AA = boot_mean_ci(onoff_ab), boot_mean_ci(onoff_AA)
rows.append(("POOLED a\u2013d (16 pairs)", np.median(onoff_ab), ci_ab, C_BLUE, 7))
rows.append(("POOLED A/A batch (16 pairs)", np.median(onoff_AA), ci_AA, C_RED, 7))

y = np.arange(len(rows))[::-1]
for yi, (label, med, ci, color, ms) in zip(y, rows):
    ax1.plot(ci, [yi, yi], color=color, lw=2.0, solid_capstyle="round", alpha=0.85)
    ax1.plot(med, yi, "o", color=color, ms=ms, zorder=3)
ax1.axvline(0, color="#666b74", lw=0.9)
ax1.axvline(0.5, color=C_RED, lw=1.3, ls="--")
ax1.text(0.5, len(rows) - 0.4, " 0.5% acceptance bound", color=C_RED, fontsize=8.5, va="center")
ax1.set_yticks(y)
ax1.set_yticklabels([r[0] for r in rows], fontsize=8.5)
ax1.set_xlabel("Paired off/on overhead (%)  \u2014 dot: median, bar: bootstrap mean 95% CI", fontsize=9)
ax1.set_title("(a) Instrumentation overhead, 8 sessions \u00d7 4 pairs\n8000 steps/pair, AB/BA alternated, 2\u00d7RTX 4090", fontsize=9.5)
ax1.set_xlim(-0.7, 2.6)
ax1.grid(axis="x", color="#d8dce2", lw=0.6, alpha=0.7)
ax1.tick_params(labelsize=8.5)
ax1.text(
    0.98, 0.02, "pooled A/A-batch upper bound 0.706% > 0.5%:\nrecipe-level acceptance still pending",
    transform=ax1.transAxes, ha="right", va="bottom", fontsize=8, color="#444a54",
)

# ---- panel (b): bias controls ----
groups = [(f"A/A {n} (GPU {gpu_label(s)})", np.median([tr["difference_pct"] for tr in s["aa_trials"]]),
           boot_mean_ci([tr["difference_pct"] for tr in s["aa_trials"]])) for n, s in aa_sessions]
groups.append(("A/A POOLED (16 pairs)", np.median(all_aa), boot_mean_ci(all_aa)))

yb = np.arange(len(groups) + 4)[::-1]
for yi, (label, med, ci) in zip(yb, groups):
    is_pooled = label.startswith("A/A POOLED")
    color = C_RED if is_pooled else C_ORANGE
    ax2.plot(ci, [yi, yi], color=color, lw=2.0, solid_capstyle="round", alpha=0.85)
    ax2.plot(med, yi, "o", color=color, ms=7 if is_pooled else 5.5, zorder=3)

for yi, (n, s) in zip(yb[-4:], aa_sessions):
    vals = [tr["difference_pct"] for tr in s["null_trials"]]
    ax2.scatter(vals, [yi] * len(vals), s=16, color=C_GRAY, alpha=0.8, zorder=2)
    ax2.plot(np.median(vals), yi, "d", color="#5b6068", ms=6, zorder=3)

ax2.axvline(0, color="#666b74", lw=0.9)
ax2.set_yticks(yb)
ax2.set_yticklabels(
    [g[0] for g in groups] + [f"off/off {n} null pairs" for n, _ in aa_sessions], fontsize=8.5,
)
ax2.set_xlabel("Difference between arms (%)  \u2014 A/A: median + CI; off/off: per-pair scatter + median", fontsize=9)
ax2.set_title("(b) Repeatability controls, A/A batch\nA/A consistent with zero (common-mode cost untested); off/off = environment drift", fontsize=9.5)
ax2.grid(axis="x", color="#d8dce2", lw=0.6, alpha=0.7)
ax2.tick_params(labelsize=8.5)
ax2.text(
    0.97, 0.04,
    "A/A pooled median +0.014%, CI [\u22120.33%, +0.17%] includes zero\n(consistent with zero; common-mode observer cost not identified);\noff/off drift \u22120.6% \u2026 +3.0% far exceeds the A/A spread",
    transform=ax2.transAxes, ha="right", va="bottom", fontsize=8, color="#444a54",
)

for ax in (ax1, ax2):
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

fig.savefig(os.path.join(HERE, "multisession-forest.png"), dpi=200, bbox_inches="tight", facecolor="white")
print("written", os.path.join(HERE, "multisession-forest.png"))
