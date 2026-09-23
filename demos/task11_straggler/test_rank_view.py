# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Missing telemetry must stay distinguishable from a completed no-alert window."""

import unittest

from render_rank_view import STAGES, build_rows, markdown


class RankViewTest(unittest.TestCase):
    def make_data(self) -> dict:
        return {
            "config": {"injection_steps": 8, "interval": 4},
            "environment": {"world_size": 2},
            "diagnosis": {"alerts": [], "uncertain": []},
            "telemetry": {"planned": 4},
            "samples": [
                {
                    "case": "control", "step": step, "rank": rank, "workload": 32,
                    "stages_ms": {stage: 1.0 for stage in STAGES},
                }
                for rank in (0, 1) for step in (0, 4)
            ],
        }

    def test_partial_rank_coverage_is_not_no_alert(self) -> None:
        data = self.make_data()
        data["samples"].pop()
        row = next(row for row in build_rows(data) if row["case"] == "control" and row["rank"] == 1)
        self.assertEqual(row["status"], "insufficient data")
        self.assertEqual(row["coverage"], "1/2")

    def test_missing_stage_is_not_no_alert(self) -> None:
        data = self.make_data()
        del data["samples"][0]["stages_ms"]["backward"]
        row = next(row for row in build_rows(data) if row["case"] == "control" and row["rank"] == 0)
        self.assertEqual(row["status"], "insufficient data")

    def test_unmeasured_failure_counters_are_not_zero(self) -> None:
        data = self.make_data()
        report = markdown(data, build_rows(data))
        self.assertIn("not recorded/not recorded", report)


if __name__ == "__main__":
    unittest.main()
