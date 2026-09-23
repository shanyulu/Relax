# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Standalone CUDA Event collector for the Task 11 mechanism experiment."""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from multiprocessing.queues import Queue
from typing import Any

import torch


@dataclass
class Sample:
    step: int
    workload: int
    slot: list[tuple[torch.cuda.Event, torch.cuda.Event]]
    spans: list[tuple[str, torch.cuda.Event, torch.cuda.Event]] = field(default_factory=list)
    opened_ns: int = field(default_factory=time.perf_counter_ns)

    def start(self, stage: str) -> None:
        start, stop = self.slot[len(self.spans)]
        start.record()
        self.spans.append((stage, start, stop))

    def end(self) -> None:
        _, _, stop = self.spans[-1]
        stop.record()


class AsyncProbe:
    """Records on the training stream; query, readout and reporting run elsewhere."""

    def __init__(
        self,
        *,
        rank: int,
        case: str,
        device: int,
        sink: Queue,
        interval: int = 8,
        capacity: int = 32,
        poll_ms: float = 1.0,
    ) -> None:
        self.rank = rank
        self.case = case
        self.device = device
        self.sink = sink
        self.interval = interval
        self.capacity = capacity
        self.poll_ms = poll_ms
        self.pending: deque[Sample] = deque()
        self.free = deque(
            [
                (torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
                for _ in range(4)
            ]
            for _ in range(capacity)
        )
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.close_deadline: float | None = None
        self.error: BaseException | None = None
        self.stats: dict[str, int | float] = {
            "planned": 0,
            "recorded": 0,
            "reported": 0,
            "dropped_pool": 0,
            "dropped_queue": 0,
            "dropped_sink": 0,
            "dropped_collector": 0,
            "dropped_shutdown": 0,
            "collector_error": 0,
            "collector_timeout": 0,
            "pending_peak": 0,
            "report_lag_max_ms": 0.0,
            "payload_bytes": 0,
        }
        self.worker = threading.Thread(target=self._collect, name=f"probe-rank-{rank}", daemon=True)
        startup_ns = time.perf_counter_ns()
        self.worker.start()
        if not self.ready.wait(timeout=10):
            raise RuntimeError("collector did not initialize within 10 seconds")
        if self.error:
            raise RuntimeError("collector failed to initialize") from self.error
        self.stats["startup_ms"] = (time.perf_counter_ns() - startup_ns) / 1e6

    def begin(self, step: int, workload: int) -> Sample | None:
        if step % self.interval:
            return None
        self.stats["planned"] += 1
        with self.lock:
            if self.stop.is_set():
                self.stats["dropped_shutdown"] += 1
                return None
            if self.error:
                self.stats["dropped_collector"] += 1
                return None
            if not self.free:
                self.stats["dropped_pool"] += 1
                return None
            slot = self.free.popleft()
            self.stats["recorded"] += 1
        return Sample(step=step, workload=workload, slot=slot)

    def submit(self, sample: Sample) -> None:
        with self.lock:
            if self.stop.is_set():
                self.stats["dropped_shutdown"] += 1
                return
            if self.error:
                self.stats["dropped_collector"] += 1
                return
            self.pending.append(sample)
            self.stats["pending_peak"] = max(self.stats["pending_peak"], len(self.pending))

    def _collect(self) -> None:
        try:
            self._collect_loop()
        except Exception as exc:
            with self.lock:
                self.error = exc
                self.stats["collector_error"] = 1
                self.stats["dropped_collector"] += len(self.pending)
                self.pending.clear()
        finally:
            self.ready.set()

    def _collect_loop(self) -> None:
        torch.cuda.set_device(self.device)
        self.ready.set()
        while not self.stop.is_set() or self.pending:
            if self.close_deadline is not None and time.monotonic() >= self.close_deadline:
                with self.lock:
                    self.stats["collector_timeout"] = int(bool(self.pending))
                    self.stats["dropped_shutdown"] += len(self.pending)
                    # Abandon these slots; incomplete Events must not return to the free pool.
                    self.pending.clear()
                return
            with self.lock:
                candidates = list(self.pending)
            for sample in candidates:
                if not sample.spans or not all(stop.query() for _, _, stop in sample.spans):
                    continue
                durations = {name: round(start.elapsed_time(stop), 4) for name, start, stop in sample.spans}
                lag = (time.perf_counter_ns() - sample.opened_ns) / 1e6
                message: dict[str, Any] = {
                    "type": "sample",
                    "case": self.case,
                    "rank": self.rank,
                    "step": sample.step,
                    "workload": sample.workload,
                    "cohort": "dp0",
                    "measurement_kind": "gpu_stream_interval",
                    "stages_ms": durations,
                    "report_lag_ms": round(lag, 4),
                }
                wire = json.dumps(message, separators=(",", ":")).encode()
                try:
                    self.sink.put_nowait(wire)
                except queue.Full:
                    self.stats["dropped_queue"] += 1
                except Exception:
                    # Telemetry transport failures must not terminate training.
                    self.stats["dropped_sink"] += 1
                else:
                    self.stats["reported"] += 1
                    self.stats["payload_bytes"] += len(wire)
                    self.stats["report_lag_max_ms"] = max(self.stats["report_lag_max_ms"], lag)
                with self.lock:
                    self.pending.remove(sample)
                    self.free.append(sample.slot)
            time.sleep(self.poll_ms / 1000)

    def close(self, timeout_secs: float = 10.0) -> dict[str, int | float]:
        if timeout_secs < 0:
            raise ValueError("close timeout must be nonnegative")
        self.close_deadline = time.monotonic() + timeout_secs
        self.stop.set()
        self.worker.join(timeout=timeout_secs + self.poll_ms / 1000 + 0.1)
        if self.worker.is_alive():
            self.stats["collector_timeout"] = 1
        self.stats["collector_alive"] = int(self.worker.is_alive())
        return dict(self.stats)
