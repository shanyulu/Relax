#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Programmatic overlap metrics from Megatron's exported chrome traces.

Reads every ``torch_profile/rank-*.json.gz`` in a trace arm's tensorboard
parent directory and computes, per rank and aggregated (per TRACE_PROTOCOL):

  compute_busy    union of non-NCCL GPU kernel intervals (µs)
  comm_busy       union of NCCL kernel intervals (µs)
  overlap_duration  measure of (compute ∩ comm) (µs)
  overlap_ratio   overlap_duration / min(compute_busy, comm_busy)
  device_idle     (traced window) − (compute ∪ comm)
  host_gap        sum of gaps between consecutive GPU-side launches
  global_sync_count  cudaDeviceSynchronize API calls (grid-wide sync proxy)

Classifier rules are fixed: a GPU event (cat == 'kernel') whose name contains
'nccl' (case-insensitive) is COMM; other 'kernel' events are COMPUTE;
'memcpy'/'memset' events are counted separately as transfer and excluded from
both busy measures. The traced window is [min(ts), max(ts+dur)] over all
device-side events.

Output: JSON on stdout (or --out). Exit 1 if no device events are found.
"""

import argparse
import gzip
import json
from pathlib import Path


def load_events(path: Path):
    with gzip.open(path, "rt", errors="replace") as fh:
        data = json.load(fh)
    return data.get("traceEvents", [])


def union(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(x) for x in merged]


def total(intervals):
    return sum(end - start for start, end in intervals)


def intersection(a, b):
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def classify(path: Path) -> dict:
    events = load_events(path)
    compute, comm, transfer = [], [], []
    global_sync = 0
    for ev in events:
        cat = str(ev.get("cat", "")).lower()
        name = str(ev.get("name", ""))
        ts, dur = ev.get("ts"), ev.get("dur")
        if ts is None or dur is None:
            continue
        if cat == "cuda_runtime" or cat == "cuda_driver":
            if "devicesynchronize" in name.lower():
                global_sync += 1
            continue
        if cat == "kernel":
            if "nccl" in name.lower():
                comm.append((ts, ts + dur))
            else:
                compute.append((ts, ts + dur))
        elif cat in ("gpu_memcpy", "memcpy", "gpu_memset", "memset"):
            transfer.append((ts, ts + dur))
    if not compute and not comm:
        return {"rank_file": path.name, "device_events": 0}
    device_events = sorted(compute + comm + transfer)
    window_start = device_events[0][0]
    window_end = max(end for _, end in device_events)
    window = window_end - window_start
    cu, cm = union(compute), union(comm)
    both = union(compute + comm)
    overlap = intersection(cu, cm)
    launches = sorted(compute + comm)
    host_gap = 0.0
    for prev, nxt in zip(launches, launches[1:]):
        gap = nxt[0] - prev[1]
        if gap > 0:
            host_gap += gap
    return {
        "rank_file": path.name,
        "device_events": len(device_events),
        "compute_kernels": len(compute),
        "comm_kernels": len(comm),
        "transfer_events": len(transfer),
        "global_sync_count": global_sync,
        "window_us": window,
        "compute_busy_us": total(cu),
        "comm_busy_us": total(cm),
        "transfer_busy_us": total(union(transfer)),
        "overlap_duration_us": total(overlap),
        "overlap_ratio": (total(overlap) / min(total(cu), total(cm))) if cu and cm and min(total(cu), total(cm)) > 0 else None,
        "device_idle_us": window - total(both),
        "host_gap_us": host_gap,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", type=Path, required=True, help="arm dir containing tensorboard/../torch_profile")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    profiles = sorted(args.arm.rglob("torch_profile/rank-*.json.gz"))
    if not profiles:
        print(json.dumps({"error": "no torch_profile exports found", "arm": str(args.arm)}))
        return 1
    ranks = [classify(p) for p in profiles]
    valid = [r for r in ranks if r.get("device_events")]
    agg = {
        "arm": str(args.arm),
        "ranks_profiled": len(valid),
        "rank_files": [r["rank_file"] for r in ranks],
        "global_sync_count_total": sum(r.get("global_sync_count", 0) for r in valid),
        "compute_busy_us_total": sum(r.get("compute_busy_us", 0) for r in valid),
        "comm_busy_us_total": sum(r.get("comm_busy_us", 0) for r in valid),
        "overlap_duration_us_total": sum(r.get("overlap_duration_us", 0) for r in valid),
        "device_idle_us_total": sum(r.get("device_idle_us", 0) for r in valid),
        "host_gap_us_total": sum(r.get("host_gap_us", 0) for r in valid),
        "per_rank": ranks,
    }
    cb, mb = agg["compute_busy_us_total"], agg["comm_busy_us_total"]
    agg["overlap_ratio_total"] = (agg["overlap_duration_us_total"] / min(cb, mb)) if cb > 0 and mb > 0 else None
    payload = json.dumps(agg, indent=2)
    if args.out:
        args.out.write_text(payload + "\n")
    print(payload[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
