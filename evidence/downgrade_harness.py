# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Real-process degradation harness for the Task 11 straggler profiler.

Unlike the unit tests, this runs the profiler through its real, environment-gated
entry point in separate OS processes that join a real ``torch.distributed``
(glue) process group, ship envelopes over real loopback TCP, and use real CUDA
event records when a GPU is present.

Waves
-----
1. collector alive   — baseline, and where detection must fire
2. collector killed  — SIGKILL mid-run: the trainer side must not slow down, the
   sender must count the failure and keep retrying
3. collector back    — a restarted collector must receive envelopes again
   (reconnect) and still judge the slow rank

Harness deviation (declared): in a real run the collector lives inside rank 0's
trainer process, which cannot be killed without killing training. Here the
collector is a separate process so the *transport* outage that the other ranks
observe can be injected reproducibly. From the workers' point of view the
topology is identical: they only know a ``host:port``.

Usage (driver mode is the default)::

    PYTHONPATH=<worktree> python downgrade_harness.py --out-dir <evidence-dir>
"""

import argparse
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

INTERVAL_NAME = "forward-backward"


def free_port() -> int:
    """Reserve and release a loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """Wait until something accepts connections on ``host:port``."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except Exception:
            time.sleep(0.05)
    return False


def wait_for_file(path: Path, timeout: float = 120.0) -> bool:
    """Wait until ``path`` exists."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def profiler_env(addr: Optional[str], output_dir: Optional[str], window_s: float) -> Dict[str, str]:
    """Environment that enables the profiler exactly as a recipe would."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "task11-c2")
    env["RELAX_STRAGGLER_ENABLE"] = "1"
    env["RELAX_STRAGGLER_WINDOW_S"] = str(window_s)
    env["RELAX_STRAGGLER_PERSIST_WINDOWS"] = "1"
    env["RELAX_STRAGGLER_WORK_TOLERANCE"] = "0.05"
    env["RELAX_STRAGGLER_REPORT_INTERVAL_S"] = "1.0"
    env["RELAX_STRAGGLER_RUN_ID"] = "downgrade-harness"
    if addr:
        env["RELAX_STRAGGLER_COLLECTOR_ADDR"] = addr
    if output_dir:
        env["RELAX_STRAGGLER_OUTPUT_DIR"] = output_dir
    return env


def run_collector(addr: str, output_dir: str, window_s: float, log_path: Path) -> int:
    """Collector process: build the runtime and idle until SIGTERM."""

    def _terminate(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"collector listening on {addr}\n")
        log.flush()
        env = profiler_env(addr, output_dir, window_s)
        os.environ.update(env)
        from relax.utils.straggler import get_straggler_runtime

        runtime = get_straggler_runtime()
        log.write(f"role={None if runtime is None else runtime.role}\n")
        log.flush()
        if runtime is None:
            return 2
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            runtime.close()
            status_path = Path(output_dir) / "collector_status.json"
            status_path.write_text(json.dumps(runtime.status(), indent=2), encoding="utf-8")
            log.write(f"collector flushed; status written to {status_path}\n")
            return 0


def wait_for_go(path: Path, timeout: float = 120.0) -> None:
    """Block until the driver creates ``path``."""
    if not wait_for_file(path, timeout):
        raise TimeoutError(f"driver never created {path}")


def run_stub(args: argparse.Namespace) -> int:
    """Join the process group as rank 0 without doing any work.

    Rank 0 is reserved for the standalone collector process, so the workers take
    ranks 1..N-1. gloo needs rank 0 to exist for the rank space to be valid, but
    it never takes part in the waves (no collectives are used).
    """
    import torch.distributed as dist
    from datetime import timedelta

    dist.init_process_group(
        backend="gloo",
        init_method=f"tcp://127.0.0.1:{args.rendezvous}",
        rank=0,
        world_size=args.world_size,
        timeout=timedelta(seconds=60),
    )
    Path(args.out).write_text("stub ready", encoding="utf-8")
    wait_for_file(Path(f"{args.out}.stop"), timeout=600)
    return 0


def run_worker(args: argparse.Namespace) -> int:
    """Worker process: join gloo, run three waves, report timings."""
    import torch.distributed as dist
    from datetime import timedelta

    out = Path(args.out)
    marker = lambda wave: Path(f"{out}.wave{wave}")  # noqa: E731
    result: Dict[str, Any] = {"rank": args.rank, "waves": {}, "notes": []}

    dist.init_process_group(
        backend="gloo",
        init_method=f"tcp://127.0.0.1:{args.rendezvous}",
        rank=args.rank,
        world_size=args.world_size,
        timeout=timedelta(seconds=60),
    )
    os.environ.update(profiler_env(args.addr, None, args.window_s))
    from relax.utils.straggler import get_straggler_runtime
    from relax.utils.straggler.identity import discover_identity

    identity = discover_identity()
    runtime = get_straggler_runtime()
    if runtime is None:
        result["notes"].append("runtime failed to start")
        out.write_text(json.dumps(result), encoding="utf-8")
        return 2
    worker_group = dist.new_group(ranks=list(range(1, args.world_size))) if args.world_size > 2 else None
    result["identity"] = identity.as_dict()
    result["role"] = runtime.role
    timers = runtime.timers
    assert timers is not None

    for wave in (1, 2, 3):
        if wave > 1:
            wait_for_go(Path(f"{out}.go{wave}"))
        if worker_group is not None:
            dist.barrier(group=worker_group)
        samples: List[float] = []
        for _ in range(args.intervals):
            if worker_group is not None:
                # A synchronous training step: no rank starts step k before every
                # rank finished step k-1. Without this the fast ranks race ahead
                # and the ranks stop sharing aggregation windows.
                dist.barrier(group=worker_group)
            start = time.perf_counter()
            handle = timers(INTERVAL_NAME, log_level=2)
            handle.start()
            _busy(args.work_ms)
            if args.rank == args.slow_rank:
                time.sleep(args.slow_extra_ms / 1000.0)
            handle.stop()
            samples.append((time.perf_counter() - start) * 1000.0)
        result["waves"][f"wave{wave}"] = summarise(samples)
        marker(wave).write_text("done", encoding="utf-8")

    result["timers"] = timers.stats()
    if runtime.sender is not None:
        result["sender"] = runtime.sender.stats()
    result["runtime_errors"] = runtime.status()["errors"]
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    runtime.close()
    try:
        dist.destroy_process_group()
    except Exception:
        pass
    return 0


def _busy(milliseconds: float) -> None:
    """Burn host time without allocating, standing in for a training interval."""
    if milliseconds <= 0:
        return
    deadline = time.perf_counter() + milliseconds / 1000.0
    while time.perf_counter() < deadline:
        pass


def summarise(samples: List[float]) -> Dict[str, float]:
    """Median/p95/min/max of a sample list."""
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[int(0.95 * (len(ordered) - 1))],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def driver(args: argparse.Namespace) -> int:
    """Run the three waves and assemble the evidence report."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    address = f"127.0.0.1:{free_port()}"
    rendezvous = free_port()
    python = args.python
    script = str(Path(__file__).resolve())
    window_s = args.window_s

    children: List[subprocess.Popen] = []
    collectors: List[subprocess.Popen] = []
    report: Dict[str, Any] = {
        "evidence_dir": str(out_dir),
        "address": address,
        "window_seconds": window_s,
        "intervals_per_wave": args.intervals,
        "work_ms": args.work_ms,
        "slow_rank": args.slow_rank,
        "slow_extra_ms": args.slow_extra_ms,
        "python": python,
        "deviation": (
            "collector runs as a separate process so the transport outage can be injected; "
            "in a real run it lives in rank 0's trainer process"
        ),
    }

    def start_collector(tag: str) -> subprocess.Popen:
        log_path = out_dir / f"collector_{tag}.log"
        with open(out_dir / f"collector_{tag}.stdout", "w", encoding="utf-8") as stream:
            process = subprocess.Popen(
                [python, script, "--role", "collector", "--addr", address, "--output-dir", str(out_dir),
                 "--window-s", str(window_s), "--log", str(log_path)],
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=profiler_env(address, str(out_dir), window_s),
            )
        collectors.append(process)
        host, port = address.split(":")
        if not wait_for_port(host, int(port), timeout=30.0):
            raise RuntimeError(f"collector {tag} never listened on {address}")
        return process

    worker_ranks = list(range(1, args.world_size))
    try:
        collector = start_collector("wave1")
        stub_out = out_dir / "stub_rank0.json"
        stub = subprocess.Popen(
            [python, script, "--role", "stub", "--rank", "0", "--world-size", str(args.world_size),
             "--rendezvous", str(rendezvous), "--out", str(stub_out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            env=profiler_env(address, None, window_s),
        )
        children.append(stub)
        # Every rank blocks in init_process_group until the whole world has
        # joined, so the workers must be launched without waiting for rank 0.
        for rank in worker_ranks:
            out = out_dir / f"worker_{rank}.json"
            with open(out_dir / f"worker_{rank}.stdout", "w", encoding="utf-8") as stream:
                process = subprocess.Popen(
                    [python, script, "--role", "worker", "--addr", address, "--rank", str(rank),
                     "--world-size", str(args.world_size), "--rendezvous", str(rendezvous),
                     "--intervals", str(args.intervals), "--work-ms", str(args.work_ms),
                     "--slow-rank", str(args.slow_rank), "--slow-extra-ms", str(args.slow_extra_ms),
                     "--window-s", str(window_s), "--out", str(out)],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    env=profiler_env(address, None, window_s),
                )
            children.append(process)

        # Wave 1 -> kill the collector while the workers are mid-flight.
        for rank in worker_ranks:
            _require(out_dir / f"worker_{rank}.json.wave1", "wave1 marker")
        report["collector_wave1_envelopes"] = _envelope_count(out_dir)
        collector.send_signal(signal.SIGKILL)
        collector.wait(timeout=10)
        report["collector_killed"] = True
        _release(out_dir, 2, worker_ranks)

        # Wave 2 -> collector is gone.
        for rank in worker_ranks:
            _require(out_dir / f"worker_{rank}.json.wave2", "wave2 marker")
        report["collector_wave2_envelopes"] = _envelope_count(out_dir)

        # Wave 3 -> collector returns on the same address.
        start_collector("wave3")
        _release(out_dir, 3, worker_ranks)
        for rank in worker_ranks:
            _require(out_dir / f"worker_{rank}.json.wave3", "wave3 marker")
        for process in children:
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                report.setdefault("notes", []).append(f"worker pid {process.pid} did not exit")
                process.kill()
        for process in collectors:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=30)  # orderly close flushes the last window
                except subprocess.TimeoutExpired:
                    process.kill()
        report["collector_wave3_envelopes"] = _envelope_count(out_dir)

        (stub_out.with_suffix(".json.stop")).write_text("stop", encoding="utf-8")
        report["worker_ranks"] = worker_ranks
        report["workers"] = [json.loads((out_dir / f"worker_{rank}.json").read_text()) for rank in worker_ranks]
        report["verdicts"] = _read_verdicts(out_dir)
        report["checks"] = evaluate(report)
        (out_dir / "downgrade_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report["checks"], indent=2))
        print(f"report: {out_dir / 'downgrade_report.json'}")
        return 0 if all(check["passed"] for check in report["checks"]) else 1
    finally:
        for process in [*children, *collectors]:
            if process.poll() is None:
                process.kill()


def _require(path: Path, label: str) -> None:
    if not wait_for_file(path, timeout=180.0):
        raise TimeoutError(f"workers never produced the {label} ({path})")


def _release(out_dir: Path, wave: int, worker_ranks: List[int]) -> None:
    for rank in worker_ranks:
        (out_dir / f"worker_{rank}.json.go{wave}").write_text("go", encoding="utf-8")


def _envelope_count(out_dir: Path) -> int:
    path = out_dir / "straggler_envelopes.jsonl"
    if not path.exists():
        return 0
    return sum(1 for _ in path.open(encoding="utf-8"))


def _read_verdicts(out_dir: Path) -> List[Dict[str, Any]]:
    path = out_dir / "straggler_verdicts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply the preregistered degradation checks to the collected data."""
    workers = report["workers"]
    checks: List[Dict[str, Any]] = []

    def median_of(rank_data: Dict[str, Any], wave: int) -> float:
        return rank_data["waves"][f"wave{wave}"]["median_ms"]

    # 1. Every worker shipped in wave 1 and reconnected in wave 3.
    roles = {worker["rank"]: worker["role"] for worker in workers}
    checks.append(
        {
            "name": "roles_assigned",
            "passed": set(roles.values()) == {"sender"} and len(roles) >= 2,
            "detail": roles,
        }
    )

    # 2. The outage was visible: senders counted errors/drops during wave 2.
    outage = {worker["rank"]: worker.get("sender", {}) for worker in workers}
    visible = all(
        stats.get("send_errors", 0) > 0 or stats.get("dropped_queue_full", 0) > 0 for stats in outage.values()
    )
    checks.append({"name": "outage_counted_not_raised", "passed": visible, "detail": outage})

    # 3. Training-side interval time did not grow while the collector was dead.
    deltas = {}
    stable = True
    for worker in workers:
        wave1 = median_of(worker, 1)
        wave2 = median_of(worker, 2)
        delta_ms = wave2 - wave1
        deltas[worker["rank"]] = round(delta_ms, 4)
        # The injected slow rank is slow by design; the check is that the outage
        # itself adds nothing beyond a small fraction of one work interval.
        if abs(delta_ms) > max(0.5, 0.2 * report["work_ms"]):
            stable = False
    checks.append({"name": "interval_time_unaffected_by_outage", "passed": stable, "detail_ms": deltas})

    # 4. Reconnect: the restarted collector received wave-3 envelopes.
    checks.append(
        {
            "name": "reconnected_after_restart",
            "passed": report["collector_wave3_envelopes"] > report["collector_wave2_envelopes"],
            "detail": {
                "wave1": report["collector_wave1_envelopes"],
                "wave2": report["collector_wave2_envelopes"],
                "wave3": report["collector_wave3_envelopes"],
            },
        }
    )

    # 5. Detection: the injected slow rank is named, with host-side attribution.
    stragglers = [verdict for verdict in report["verdicts"] if verdict["kind"] == "straggler"]
    named = {verdict["rank"] for verdict in stragglers}
    attribution = sorted({verdict["reason"] for verdict in stragglers})
    checks.append(
        {
            "name": "slow_rank_detected_with_attribution",
            "passed": bool(stragglers)
            and named == {report["slow_rank"]}
            and all(reason in {"gpu_stream_stall", "host_only_stall"} for reason in attribution),
            "detail": {
                "slow_rank": report["slow_rank"],
                "named_ranks": sorted(named),
                "verdict_count": len(stragglers),
                "deviations": [round(verdict["deviation"], 3) for verdict in stragglers[:5]],
                "attribution": attribution,
            },
        }
    )

    # 5b. Coverage gaps are counted rather than guessed.
    status_path = Path(report["evidence_dir"]) / "collector_status.json"
    coverage: Dict[str, Any] = {}
    if status_path.exists():
        collector_status = json.loads(status_path.read_text(encoding="utf-8"))
        collector_stats = collector_status.get("collector", {})
        coverage = {
            key: collector_stats.get(key)
            for key in (
                "windows_closed",
                "warmup_windows_skipped",
                "incomplete_windows",
                "single_rank_windows",
                "cohort_stage_pairs",
                "uncertain_judgements",
                "stragglers_reported",
                "recoveries_reported",
                "envelopes",
            )
        }
    checks.append(
        {
            "name": "coverage_is_counted",
            "passed": bool(coverage) and coverage.get("windows_closed", 0) > 0,
            "detail": coverage,
        }
    )

    # 6. No unbalanced start/stop and no sink errors on the trainer side.
    timer_stats = {worker["rank"]: worker.get("timers", {}) for worker in workers}
    clean = all(
        stats.get("unbalanced_start", 0) == 0
        and stats.get("unbalanced_stop", 0) == 0
        and stats.get("sink_errors", 0) == 0
        for stats in timer_stats.values()
    )
    checks.append({"name": "timer_bookkeeping_clean", "passed": clean, "detail": timer_stats})

    # 7. No worker process failed.
    checks.append(
        {
            "name": "no_worker_crashed",
            "passed": all(worker.get("runtime_errors", 1) == 0 for worker in workers),
            "detail": {worker["rank"]: worker.get("runtime_errors") for worker in workers},
        }
    )
    return checks


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", default="driver", choices=["driver", "collector", "worker", "stub"])
    parser.add_argument("--out-dir", default="/root/autodl-tmp/relax-work/task11_evidence/downgrade")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--addr", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--log", default="/dev/null")
    parser.add_argument("--rank", type=int, default=0)
    parser.add_argument("--world-size", type=int, default=4)
    parser.add_argument("--rendezvous", type=int, default=0)
    parser.add_argument("--intervals", type=int, default=400)
    parser.add_argument("--work-ms", type=float, default=1.0)
    parser.add_argument("--slow-rank", type=int, default=3)
    parser.add_argument("--slow-extra-ms", type=float, default=12.0)
    parser.add_argument("--window-s", type=float, default=0.25)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    if args.role == "collector":
        return run_collector(args.addr, args.output_dir, args.window_s, Path(args.log))
    if args.role == "worker":
        return run_worker(args)
    if args.role == "stub":
        return run_stub(args)
    return driver(args)


if __name__ == "__main__":
    sys.exit(main())