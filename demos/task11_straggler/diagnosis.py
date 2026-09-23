# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Compare only equivalent, present rank samples."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any


class Diagnosis:
    def __init__(
        self,
        world_size: int,
        ratio: float = 1.4,
        absolute_ms: float = 0.02,
        persistence: int = 2,
        sampling_interval: int = 4,
        max_pending_windows: int = 128,
        max_history: int = 256,
        max_cases: int = 64,
    ) -> None:
        if world_size < 2 or ratio <= 1 or absolute_ms < 0 or persistence < 1 or sampling_interval < 1:
            raise ValueError("invalid diagnosis configuration")
        if min(max_pending_windows, max_history, max_cases) < 1:
            raise ValueError("diagnosis bounds must be positive")
        self.world_size = world_size
        self.ratio = ratio
        self.absolute_ms = absolute_ms
        self.persistence = persistence
        self.sampling_interval = sampling_interval
        self.max_pending_windows = max_pending_windows
        self.max_history = max_history
        self.max_cases = max_cases
        self.windows: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
        self.last_complete_step: dict[str, int] = {}
        self.streaks: dict[tuple[str, int, str], int] = defaultdict(int)
        self.alerts: list[dict[str, Any]] = []
        self.uncertain: list[dict[str, Any]] = []
        self.alert_count = 0
        self.uncertain_count = 0
        self.duplicate_count = 0
        self.complete_windows = 0

    def _remember(self, records: list[dict[str, Any]], row: dict[str, Any]) -> None:
        records.append(row)
        if len(records) > self.max_history:
            del records[0]

    def _uncertain(self, case: str, step: int, reason: str) -> None:
        self.uncertain_count += 1
        self._remember(self.uncertain, {"case": case, "step": step, "reason": reason})

    def _reset_streaks(self, case: str) -> None:
        for key in [key for key in self.streaks if key[0] == case]:
            del self.streaks[key]

    def ingest(self, sample: dict[str, Any]) -> None:
        case, step, rank = sample["case"], sample["step"], sample["rank"]
        key = (case, step)
        if step <= self.last_complete_step.get(case, -1):
            self._uncertain(case, step, "late_window")
            return
        window = self.windows.setdefault(key, {})
        if rank in window:
            self.duplicate_count += 1
            return
        window[rank] = sample
        while len(self.windows) > self.max_pending_windows:
            expired_case, expired_step = next(iter(self.windows))
            del self.windows[(expired_case, expired_step)]
            self._uncertain(expired_case, expired_step, "missing_peer")
        if len(window) != self.world_size:
            return
        self.complete_windows += 1
        rows = list(window.values())
        del self.windows[key]
        for pending_case, pending_step in list(self.windows):
            if pending_case == case and pending_step < step:
                del self.windows[(pending_case, pending_step)]
                self._uncertain(pending_case, pending_step, "missing_peer")
        previous = self.last_complete_step.get(case)
        if previous is not None and step != previous + self.sampling_interval:
            self._reset_streaks(case)
        if case not in self.last_complete_step and len(self.last_complete_step) >= self.max_cases:
            oldest = next(iter(self.last_complete_step))
            del self.last_complete_step[oldest]
            self._reset_streaks(oldest)
        self.last_complete_step[case] = step
        if len({row["cohort"] for row in rows}) != 1:
            self._reset_streaks(case)
            self._uncertain(case, step, "non_equivalent_cohort")
            return
        if max(row["workload"] for row in rows) > 1.05 * min(row["workload"] for row in rows):
            self._reset_streaks(case)
            self._uncertain(case, step, "workload_imbalance")
            return
        stages = set.intersection(*(set(row["stages_ms"]) for row in rows))
        if any(set(row["stages_ms"]) != stages for row in rows):
            self._reset_streaks(case)
            self._uncertain(case, step, "stage_mismatch")
            return
        for streak_key in [key for key in self.streaks if key[0] == case and key[2] not in stages]:
            del self.streaks[streak_key]
        candidates: list[dict[str, Any]] = []
        for stage in stages:
            for row in rows:
                peers = [other["stages_ms"][stage] for other in rows if other["rank"] != row["rank"]]
                reference = statistics.median(peers)
                observed = row["stages_ms"][stage]
                streak_key = (key[0], row["rank"], stage)
                slow = observed >= reference * self.ratio and observed - reference >= self.absolute_ms
                self.streaks[streak_key] = self.streaks[streak_key] + 1 if slow else 0
                if self.streaks[streak_key] == self.persistence:
                    candidates.append(
                        {
                            "case": key[0],
                            "step": key[1],
                            "rank": row["rank"],
                            "stage": stage,
                            "observed_ms": observed,
                            "peer_median_ms": round(reference, 4),
                            "ratio": round(observed / reference, 3) if reference else None,
                            "evidence": "persistent_stage_slowdown",
                            "cause": "undetermined",
                        }
                    )
        for candidate in candidates:
            if candidate["stage"] == "collective_interval" and any(
                other["rank"] != candidate["rank"] and other["stage"] in ("forward", "backward")
                for other in candidates
            ):
                candidate["evidence"] = "correlated_peer_wait"
                candidate["cause"] = "peer_compute_delay_possible"
            self.alert_count += 1
            self._remember(self.alerts, candidate)

    def summary(self) -> dict[str, Any]:
        return {
            "complete_windows": self.complete_windows,
            "incomplete_windows": len(self.windows),
            "alert_count": self.alert_count,
            "uncertain_count": self.uncertain_count,
            "duplicate_count": self.duplicate_count,
            "alerts": self.alerts,
            "uncertain": self.uncertain,
        }
