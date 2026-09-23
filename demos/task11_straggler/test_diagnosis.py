# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU contract checks for comparison and missing data."""

import unittest

from diagnosis import Diagnosis


def sample(case: str, step: int, rank: int, ms: float, workload: int = 32) -> dict:
    return {
        "type": "sample",
        "case": case,
        "step": step,
        "rank": rank,
        "workload": workload,
        "cohort": "dp0",
        "stages_ms": {"forward": ms},
    }


class DiagnosisTest(unittest.TestCase):
    def test_persistent_slow_rank_has_peer_evidence(self) -> None:
        detector = Diagnosis(2)
        for step in (0, 4):
            detector.ingest(sample("compute", step, 0, 3.0))
            detector.ingest(sample("compute", step, 1, 9.0))
        self.assertEqual(len(detector.alerts), 1)
        self.assertEqual(detector.alerts[0]["rank"], 1)
        self.assertEqual(detector.alerts[0]["stage"], "forward")
        self.assertEqual(detector.alerts[0]["cause"], "undetermined")

    def test_missing_peer_does_not_become_zero(self) -> None:
        detector = Diagnosis(2)
        detector.ingest(sample("missing", 0, 1, 90.0))
        self.assertEqual(detector.summary()["incomplete_windows"], 1)
        self.assertEqual(detector.alerts, [])

    def test_load_skew_is_not_hardware_verdict(self) -> None:
        detector = Diagnosis(2)
        for step in (0, 4):
            detector.ingest(sample("load", step, 0, 3.0, 32))
            detector.ingest(sample("load", step, 1, 9.0, 64))
        self.assertEqual(detector.alerts, [])
        self.assertEqual([row["reason"] for row in detector.uncertain], ["workload_imbalance"] * 2)

    def test_non_equivalent_cohort_is_not_compared(self) -> None:
        detector = Diagnosis(2)
        first = sample("cohort", 0, 0, 3.0)
        second = sample("cohort", 0, 1, 9.0)
        second["cohort"] = "different"
        detector.ingest(first)
        detector.ingest(second)
        self.assertEqual(detector.uncertain[0]["reason"], "non_equivalent_cohort")

    def test_peer_wait_is_secondary_evidence(self) -> None:
        detector = Diagnosis(2)
        for step in (0, 4):
            first = sample("peer_wait", step, 0, 1.0)
            second = sample("peer_wait", step, 1, 3.0)
            first["stages_ms"]["collective_interval"] = 5.0
            second["stages_ms"]["collective_interval"] = 1.0
            detector.ingest(first)
            detector.ingest(second)
        wait = next(row for row in detector.alerts if row["stage"] == "collective_interval")
        self.assertEqual(wait["evidence"], "correlated_peer_wait")
        self.assertEqual(wait["cause"], "peer_compute_delay_possible")

    def test_twofold_short_forward_slowdown_is_detected(self) -> None:
        detector = Diagnosis(2)
        for step in (0, 4):
            detector.ingest(sample("short_forward", step, 0, 0.056))
            detector.ingest(sample("short_forward", step, 1, 0.112))
        self.assertEqual([(row["rank"], row["step"]) for row in detector.alerts], [(1, 4)])

    def test_incomparable_window_breaks_persistence(self) -> None:
        detector = Diagnosis(2)
        for step, workload in ((0, 32), (4, 64), (8, 32)):
            detector.ingest(sample("gap", step, 0, 1.0))
            detector.ingest(sample("gap", step, 1, 3.0, workload))
        self.assertEqual(detector.alerts, [])
        detector.ingest(sample("gap", 12, 0, 1.0))
        detector.ingest(sample("gap", 12, 1, 3.0))
        self.assertEqual([row["step"] for row in detector.alerts], [12])

    def test_missing_or_late_peer_does_not_create_persistence(self) -> None:
        detector = Diagnosis(2, sampling_interval=4)
        detector.ingest(sample("late", 0, 0, 1.0))
        detector.ingest(sample("late", 0, 1, 3.0))
        detector.ingest(sample("late", 4, 0, 1.0))
        detector.ingest(sample("late", 8, 0, 1.0))
        detector.ingest(sample("late", 8, 1, 3.0))
        detector.ingest(sample("late", 4, 1, 3.0))
        self.assertEqual(detector.alerts, [])
        self.assertEqual(detector.summary()["incomplete_windows"], 0)
        self.assertEqual({row["reason"] for row in detector.uncertain}, {"missing_peer", "late_window"})

    def test_incomplete_windows_and_history_are_bounded(self) -> None:
        detector = Diagnosis(2, max_pending_windows=3, max_history=4)
        for step in range(20):
            detector.ingest(sample("missing", step, 0, 1.0))
        self.assertEqual(detector.summary()["incomplete_windows"], 3)
        self.assertEqual(detector.summary()["uncertain_count"], 17)
        self.assertEqual(len(detector.uncertain), 4)


if __name__ == "__main__":
    unittest.main()
