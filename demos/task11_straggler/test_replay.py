# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Verify that the replay distinguishes measured data from a receiver drop."""

import unittest

from render_replay import replay_payload


class ReplayTest(unittest.TestCase):
    def test_receiver_drop_creates_missing_peer_not_slowdown(self) -> None:
        rows = [
            {
                "case": "compute_recovery", "step": step, "rank": rank, "cohort": "dp0",
                "workload": 48, "stages_ms": {"forward": 0.1 if rank == 0 else 0.2},
            }
            for step in (0, 4, 8, 12)
            for rank in (0, 1)
        ]
        result = {
            "environment": {"world_size": 2},
            "config": {"interval": 4, "ratio": 1.4, "absolute_ms": 0.02},
            "samples": rows,
            "diagnosis": {"alerts": [], "uncertain": []},
            "telemetry": {"planned": 8, "received": 8},
            "paired_parameter_mismatches": 0,
            "max_paired_final_loss_difference": 0,
            "scope": "test fixture", "source_sha256": {},
        }
        replay = replay_payload(result)
        missing = replay["missing_peer_simulation"]
        self.assertEqual((missing["step"], missing["rank"]), (8, 1))
        self.assertIn("missing_peer", [row["reason"] for row in missing["uncertain"]])
        self.assertFalse(any(row["step"] >= 8 for row in missing["alerts"]))
        self.assertEqual(len(replay["cases"][0]["frames"][2]["rows"]), 2)

    def test_stage_mismatch_is_not_comparable(self) -> None:
        rows = [
            {
                "case": "control", "step": 0, "rank": 0, "cohort": "dp0",
                "workload": 48, "stages_ms": {"forward": 0.1, "backward": 0.2},
            },
            {
                "case": "control", "step": 0, "rank": 1, "cohort": "dp0",
                "workload": 48, "stages_ms": {"forward": 0.1},
            },
        ]
        result = {
            "environment": {"world_size": 2},
            "config": {"interval": 4, "ratio": 1.4, "absolute_ms": 0.02},
            "samples": rows,
            "diagnosis": {"alerts": [], "uncertain": []},
            "telemetry": {"planned": 2, "received": 2},
            "paired_parameter_mismatches": 0,
            "max_paired_final_loss_difference": 0,
            "scope": "test fixture", "source_sha256": {},
        }
        replay = replay_payload(result)
        self.assertFalse(replay["cases"][0]["frames"][0]["comparable"])


if __name__ == "__main__":
    unittest.main()
