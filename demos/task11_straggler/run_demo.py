# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Run a local multi-GPU Task 11 mechanism experiment; no Relax runtime needed."""

from __future__ import annotations

import argparse
import json
import hashlib
import multiprocessing as mp
import platform
import queue
import random
import socket
import statistics
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import torch
import torch.distributed as dist
from torch import nn

from diagnosis import Diagnosis
from probe import AsyncProbe


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def shutdown_workers(children: list[mp.Process], sink: mp.Queue, *, terminate: bool) -> None:
    """Release child processes and the result queue on both success and failure."""
    if terminate:
        for child in children:
            if child.is_alive():
                child.terminate()
    for child in children:
        child.join(timeout=5)
    for child in children:
        if child.is_alive() and hasattr(child, "kill"):
            child.kill()
            child.join(timeout=5)
    sink.close()
    sink.join_thread()


def train_run(
    *,
    case: str,
    rank: int,
    device: int,
    model: nn.Module,
    initial: dict[str, torch.Tensor],
    batch: torch.Tensor,
    larger_batch: torch.Tensor,
    steps: int,
    interval: int,
    sink: mp.Queue,
    injection: str | None = None,
    compute_extra_forwards: int = 1,
    observe: bool = False,
) -> dict[str, Any]:
    with torch.no_grad():
        for name, value in model.state_dict().items():
            value.copy_(initial[name])
    optimizer = torch.optim.SGD(model.parameters(), lr=0.0002)
    probe = AsyncProbe(rank=rank, case=case, device=device, sink=sink, interval=interval) if observe else None
    inputs = larger_batch if injection == "load_skew" and rank == 1 else batch
    dist.barrier()
    torch.cuda.synchronize()
    started = time.perf_counter()
    last_loss: torch.Tensor | None = None
    for step in range(steps):
        sample = probe.begin(step, workload=inputs.shape[0]) if probe else None
        optimizer.zero_grad(set_to_none=True)
        if sample:
            sample.start("forward")
        output = model(inputs)
        if (
            rank == 1
            and (
                injection == "compute_slow"
                or (injection == "compute_recovery" and steps // 4 <= step < 3 * steps // 4)
            )
        ):
            # Extra real GPU work; not a delay fabricated in the measurements.
            for _ in range(compute_extra_forwards):
                model(inputs)
        loss = output.square().mean()
        if sample:
            sample.end()
            sample.start("backward")
        loss.backward()
        if sample:
            sample.end()
            sample.start("collective_interval")
        if injection == "host_stall" and rank == 1:
            time.sleep(0.006)
        for parameter in model.parameters():
            if parameter.grad is not None:
                dist.all_reduce(parameter.grad, op=dist.ReduceOp.AVG)
        if sample:
            sample.end()
            sample.start("optimizer")
        optimizer.step()
        if sample:
            sample.end()
            probe.submit(sample)
        last_loss = loss
    torch.cuda.synchronize()
    probe_stats = probe.close() if probe else None
    elapsed = time.perf_counter() - started
    parameter_hash = hashlib.sha256()
    for parameter in model.parameters():
        parameter_hash.update(parameter.detach().contiguous().cpu().numpy().tobytes())
    dist.barrier()
    return {
        "type": "run",
        "case": case,
        "rank": rank,
        "elapsed_s": elapsed,
        "final_loss": float(last_loss.item()),
        "parameter_sha256": parameter_hash.hexdigest(),
        "probe": probe_stats,
        "injection": injection,
    }


def worker(rank: int, world: int, port: int, args: argparse.Namespace, sink: mp.Queue) -> None:
    torch.cuda.set_device(rank)
    dist.init_process_group(
        backend="nccl",
        init_method=f"tcp://127.0.0.1:{port}",
        rank=rank,
        world_size=world,
        timeout=timedelta(minutes=5),
        device_id=torch.device("cuda", rank),
    )
    try:
        torch.manual_seed(2026)
        model = nn.Sequential(
            nn.Linear(args.dim, args.dim * 2),
            nn.GELU(),
            nn.Linear(args.dim * 2, args.dim),
        ).cuda()
        initial = {name: value.detach().clone() for name, value in model.state_dict().items()}
        torch.manual_seed(19 + rank)
        batch = torch.randn(args.batch, args.dim, device="cuda")
        larger_batch = torch.randn(args.batch * 2, args.dim, device="cuda")
        train_run(
            case="warmup",
            rank=rank,
            device=rank,
            model=model,
            initial=initial,
            batch=batch,
            larger_batch=larger_batch,
            steps=args.warmup,
            interval=args.interval,
            sink=sink,
        )
        for pair in range(max(args.pairs, args.null_pairs, args.aa_pairs)):
            # AB/BA ordering reduces drift from clocks, caches and temperature.
            if pair < args.pairs:
                for mode in (("off", "on") if pair % 2 == 0 else ("on", "off")):
                    result = train_run(
                        case=f"bench_{pair}_{mode}",
                        rank=rank,
                        device=rank,
                        model=model,
                        initial=initial,
                        batch=batch,
                        larger_batch=larger_batch,
                        steps=args.steps,
                        interval=args.interval,
                        sink=sink,
                        observe=mode == "on",
                    )
                    sink.put(result)
            if pair < args.null_pairs:
                for repeat in ("first", "second"):
                    result = train_run(
                        case=f"null_{pair}_{repeat}",
                        rank=rank,
                        device=rank,
                        model=model,
                        initial=initial,
                        batch=batch,
                        larger_batch=larger_batch,
                        steps=args.steps,
                        interval=args.interval,
                        sink=sink,
                    )
                    sink.put(result)
            if pair < args.aa_pairs:
                # A/A control: both arms run with the observer active. The
                # difference isolates measurement noise under the instrumented
                # configuration, complementing the off/off null pairs.
                for repeat in ("first", "second"):
                    result = train_run(
                        case=f"aa_{pair}_{repeat}",
                        rank=rank,
                        device=rank,
                        model=model,
                        initial=initial,
                        batch=batch,
                        larger_batch=larger_batch,
                        steps=args.steps,
                        interval=args.interval,
                        sink=sink,
                        observe=True,
                    )
                    sink.put(result)
        for injection in ("control", "compute_slow", "compute_recovery", "load_skew", "host_stall"):
            result = train_run(
                case=injection,
                rank=rank,
                device=rank,
                model=model,
                initial=initial,
                batch=batch,
                larger_batch=larger_batch,
                steps=args.injection_steps,
                interval=args.interval,
                sink=sink,
                injection=None if injection == "control" else injection,
                compute_extra_forwards=args.compute_extra_forwards,
                observe=True,
            )
            sink.put(result)
    finally:
        dist.destroy_process_group()
        sink.put({"type": "done", "rank": rank})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpus", type=int, default=2)
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--null-pairs", type=int, default=0)
    parser.add_argument(
        "--aa-pairs",
        type=int,
        default=0,
        help="A/A control pairs: both arms run with the observer active",
    )
    parser.add_argument("--steps", type=int, default=140)
    parser.add_argument("--injection-steps", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=12)
    parser.add_argument("--interval", type=int, default=4)
    parser.add_argument("--ratio", type=float, default=1.4)
    parser.add_argument("--absolute-ms", type=float, default=0.02)
    parser.add_argument("--compute-extra-forwards", type=int, default=1)
    parser.add_argument("--batch", type=int, default=48)
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available() or args.gpus > torch.cuda.device_count() or args.gpus < 2:
        parser.error("need at least two available CUDA GPUs")
    if min(args.pairs, args.steps, args.injection_steps, args.interval, args.batch, args.dim) < 1:
        parser.error("all counts must be positive")
    if args.null_pairs < 0:
        parser.error("null pairs cannot be negative")
    if args.aa_pairs < 0:
        parser.error("aa pairs cannot be negative")
    if args.compute_extra_forwards < 1:
        parser.error("compute-extra-forwards must be positive")
    context = mp.get_context("spawn")
    sink = context.Queue(maxsize=512)
    port = free_port()
    children = [context.Process(target=worker, args=(rank, args.gpus, port, args, sink)) for rank in range(args.gpus)]
    for child in children:
        child.start()
    diagnosis = Diagnosis(args.gpus, ratio=args.ratio, absolute_ms=args.absolute_ms, sampling_interval=args.interval)
    runs: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    finished: set[int] = set()
    workers_ok = False
    try:
        deadline = time.monotonic() + 600
        while len(finished) < args.gpus and time.monotonic() < deadline:
            try:
                item = sink.get(timeout=1)
            except queue.Empty:
                if any(child.exitcode not in (None, 0) for child in children):
                    break
                continue
            if isinstance(item, bytes):
                item = json.loads(item)
            if item["type"] == "sample":
                samples.append(item)
                diagnosis.ingest(item)
            elif item["type"] == "run":
                runs.append(item)
            else:
                finished.add(item["rank"])
        for child in children:
            child.join(timeout=5)
        bad = [child.exitcode for child in children if child.exitcode != 0]
        if bad or len(finished) != args.gpus or any(child.is_alive() for child in children):
            raise RuntimeError(f"workers failed or timed out: exit codes={bad}, finished={sorted(finished)}")
        workers_ok = True
    finally:
        shutdown_workers(children, sink, terminate=not workers_ok)
    by_case: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_case.setdefault(run["case"], []).append(run)
    expected = args.gpus * (args.pairs * 2 + args.null_pairs * 2 + args.aa_pairs * 2 + 5)
    if len(runs) != expected or any(len(group) != args.gpus for group in by_case.values()):
        raise RuntimeError(f"missing run results: got {len(runs)} of {expected}")
    paired: list[dict[str, Any]] = []
    for pair in range(args.pairs):
        off = max(row["elapsed_s"] for row in by_case[f"bench_{pair}_off"])
        on = max(row["elapsed_s"] for row in by_case[f"bench_{pair}_on"])
        paired.append({"pair": pair, "off_s": off, "on_s": on, "overhead_pct": (on / off - 1) * 100})
    null_trials: list[dict[str, Any]] = []
    for pair in range(args.null_pairs):
        first = max(row["elapsed_s"] for row in by_case[f"null_{pair}_first"])
        second = max(row["elapsed_s"] for row in by_case[f"null_{pair}_second"])
        null_trials.append(
            {"pair": pair, "first_s": first, "second_s": second, "difference_pct": (second / first - 1) * 100}
        )
    aa_trials: list[dict[str, Any]] = []
    for pair in range(args.aa_pairs):
        first = max(row["elapsed_s"] for row in by_case[f"aa_{pair}_first"])
        second = max(row["elapsed_s"] for row in by_case[f"aa_{pair}_second"])
        aa_trials.append(
            {"pair": pair, "first_s": first, "second_s": second, "difference_pct": (second / first - 1) * 100}
        )
    overheads = [row["overhead_pct"] for row in paired]
    rng = random.Random(2026)
    bootstrap = sorted(statistics.mean(rng.choices(overheads, k=len(overheads))) for _ in range(10000))
    observed = [row for row in runs if row["probe"]]
    result = {
        "scope": "standalone mechanism; not a Relax recipe or official acceptance",
        "environment": {
            "gpu": [torch.cuda.get_device_name(index) for index in range(args.gpus)],
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "python": platform.python_version(),
            "world_size": args.gpus,
        },
        "source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("run_demo.py", "probe.py", "diagnosis.py")
        },
        "config": {key: value for key, value in vars(args).items() if key != "output"},
        "paired_trials": paired,
        "null_trials": null_trials,
        "aa_trials": aa_trials,
        "max_paired_final_loss_difference": max(
            abs(
                next(row["final_loss"] for row in by_case[f"bench_{pair}_on"] if row["rank"] == rank)
                - next(row["final_loss"] for row in by_case[f"bench_{pair}_off"] if row["rank"] == rank)
            )
            for pair in range(args.pairs)
            for rank in range(args.gpus)
        ),
        "paired_parameter_mismatches": sum(
            next(row["parameter_sha256"] for row in by_case[f"bench_{pair}_on"] if row["rank"] == rank)
            != next(row["parameter_sha256"] for row in by_case[f"bench_{pair}_off"] if row["rank"] == rank)
            for pair in range(args.pairs)
            for rank in range(args.gpus)
        ),
        "overhead_median_pct": statistics.median(row["overhead_pct"] for row in paired),
        "overhead_range_pct": [min(row["overhead_pct"] for row in paired), max(row["overhead_pct"] for row in paired)],
        "bootstrap_mean_95pct_interval_pct": [bootstrap[249], bootstrap[9749]],
        "telemetry": {
            "planned": sum(row["probe"]["planned"] for row in observed),
            "reported": sum(row["probe"]["reported"] for row in observed),
            "received": len(samples),
            "dropped_pool": sum(row["probe"]["dropped_pool"] for row in observed),
            "dropped_queue": sum(row["probe"]["dropped_queue"] for row in observed),
            "dropped_sink": sum(row["probe"]["dropped_sink"] for row in observed),
            "dropped_collector": sum(row["probe"]["dropped_collector"] for row in observed),
            "dropped_shutdown": sum(row["probe"]["dropped_shutdown"] for row in observed),
            "collector_error": sum(row["probe"]["collector_error"] for row in observed),
            "collector_timeout": sum(row["probe"]["collector_timeout"] for row in observed),
            "collector_alive": sum(row["probe"]["collector_alive"] for row in observed),
            "json_payload_bytes": sum(row["probe"]["payload_bytes"] for row in observed),
            "max_report_lag_ms": max(row["probe"]["report_lag_max_ms"] for row in observed),
        },
        "diagnosis": diagnosis.summary(),
        "samples": samples,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "scope",
                    "overhead_median_pct",
                    "overhead_range_pct",
                    "bootstrap_mean_95pct_interval_pct",
                    "max_paired_final_loss_difference",
                    "paired_parameter_mismatches",
                    "telemetry",
                    "diagnosis",
                )
            },
            indent=2,
        )
    )
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
