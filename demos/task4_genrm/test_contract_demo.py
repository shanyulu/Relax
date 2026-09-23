# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Contract invariants for the mock GenRM lifecycle."""

import unittest

from contract_demo import ContractDemo, scripted_scenarios


class ContractDemoTest(unittest.TestCase):
    def test_scripted_contract(self) -> None:
        checks = scripted_scenarios()["checks"]
        self.assertTrue(all(value is True for key, value in checks.items() if key != "final_capacity"))
        self.assertEqual(checks["final_capacity"], [1, 1])

    def test_health_gates_route_and_late_ack(self) -> None:
        demo = ContractDemo()
        request_id = demo.request("out", 2)["request_id"]
        self.assertEqual(demo.scale_out(request_id, health_ok=False), "FAILED")
        self.assertEqual(demo.current, 1)
        self.assertEqual(demo.ready, 1)
        self.assertNotIn("manager-pg-1", demo.pg_live)
        self.assertFalse(demo.late_health_ack("genrm-1"))

    def test_drain_waits_for_accepted_call_and_backend(self) -> None:
        demo = ContractDemo()
        demo.scale_out(demo.request("out", 2)["request_id"])
        self.assertTrue(demo.admit("genrm-1", "score"))
        request_id = demo.request("in", 1)["request_id"]
        demo.close_admission(request_id)
        self.assertEqual(demo.current, 2)
        self.assertEqual(demo.ready, 1)
        self.assertFalse(demo.admit("genrm-1", "stale"))
        self.assertEqual(demo.finish_scale_in(request_id), "DRAINING")
        demo.complete("genrm-1", "score")
        self.assertEqual(demo.finish_scale_in(request_id, backend_idle=False), "DRAINING")
        self.assertEqual(demo.finish_scale_in(request_id), "COMPLETED")
        self.assertEqual(demo.current, 1)
        self.assertIn("training-pg", demo.pg_live)

    def test_absolute_target_with_multiple_new_replicas(self) -> None:
        demo = ContractDemo()
        demo.scale_out(demo.request("out", 3)["request_id"])
        self.assertEqual((demo.current, demo.ready), (3, 3))
        request_id = demo.request("in", 1)["request_id"]
        demo.close_admission(request_id)
        self.assertEqual(demo.finish_scale_in(request_id), "PENDING")
        self.assertEqual(demo.request("out", 3)["http"], 409)
        demo.close_admission(request_id)
        self.assertEqual(demo.finish_scale_in(request_id), "COMPLETED")
        self.assertEqual((demo.current, demo.ready), (1, 1))

    def test_invalid_and_unresolved_cleanup(self) -> None:
        demo = ContractDemo()
        self.assertEqual(demo.request("out", True)["http"], 422)
        self.assertEqual(demo.request("in", 0)["http"], 400)
        self.assertEqual(demo.get_status("missing")["http"], 404)
        request_id = demo.request("out", 2)["request_id"]
        demo.scale_out(request_id, health_ok=False, cleanup_ok=False)
        self.assertIn("manager-pg-1", demo.pg_live)
        self.assertEqual(demo.request("out", 2)["http"], 409)
        self.assertEqual(demo.retry_cleanup(request_id), "RECONCILED")
        retry = demo.request("out", 2)
        self.assertEqual(demo.scale_out(retry["request_id"]), "ACTIVE")

    def test_failed_drain_requires_explicit_retry(self) -> None:
        demo = ContractDemo()
        demo.scale_out(demo.request("out", 2)["request_id"])
        request_id = demo.request("in", 1)["request_id"]
        demo.close_admission(request_id)
        demo.fail_drain(request_id)
        self.assertTrue(demo.paused)
        self.assertIn("manager-pg-1", demo.pg_live)
        self.assertEqual(demo.retry_scale_in(request_id), "COMPLETED")
        self.assertFalse(demo.paused)
        self.assertEqual((demo.current, demo.ready), (1, 1))


if __name__ == "__main__":
    unittest.main()
