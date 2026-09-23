# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Exercise bounded Event and backpressure behavior on a real CUDA device."""

import queue
import threading
import unittest

import torch

from probe import AsyncProbe


class FullSink:
    def put_nowait(self, _payload: bytes) -> None:
        raise queue.Full()


class BrokenSink:
    def put_nowait(self, _payload: bytes) -> None:
        raise OSError("telemetry receiver unavailable")


class BrokenEvent:
    def query(self) -> bool:
        raise RuntimeError("event readout failed")


class NeverReadyEvent:
    def query(self) -> bool:
        return False


class SignallingBrokenSink:
    def __init__(self) -> None:
        self.attempted = threading.Event()

    def put_nowait(self, _payload: bytes) -> None:
        self.attempted.set()
        raise OSError("telemetry receiver unavailable")


@unittest.skipUnless(torch.cuda.is_available(), "requires CUDA")
class ProbeTest(unittest.TestCase):
    def test_pool_and_queue_saturation_drop_telemetry(self) -> None:
        torch.cuda.set_device(0)
        probe = AsyncProbe(rank=0, case="failure", device=0, sink=FullSink(), interval=1, capacity=1)
        sample = probe.begin(0, workload=8)
        self.assertIsNotNone(sample)
        self.assertIsNone(probe.begin(1, workload=8))
        sample.start("forward")
        torch.ones(128, device="cuda").square()
        sample.end()
        probe.submit(sample)
        torch.cuda.synchronize()
        stats = probe.close()
        self.assertGreaterEqual(stats["startup_ms"], 0)
        self.assertEqual(stats["dropped_pool"], 1)
        self.assertEqual(stats["dropped_queue"], 1)
        self.assertEqual(stats["reported"], 0)

    def test_transport_failure_drops_sample_without_failing_close(self) -> None:
        probe = AsyncProbe(rank=0, case="transport_failure", device=0, sink=BrokenSink(), interval=1, capacity=1)
        sample = probe.begin(0, workload=8)
        self.assertIsNotNone(sample)
        sample.start("forward")
        torch.ones(128, device="cuda").square()
        sample.end()
        probe.submit(sample)
        torch.cuda.synchronize()
        stats = probe.close()
        self.assertEqual(stats["dropped_sink"], 1)
        self.assertEqual(stats["collector_error"], 0)
        self.assertEqual(stats["reported"], 0)

    def test_collector_failure_disables_observation_without_failing_close(self) -> None:
        probe = AsyncProbe(rank=0, case="collector_failure", device=0, sink=FullSink(), interval=1, capacity=1)
        sample = probe.begin(0, workload=8)
        self.assertIsNotNone(sample)
        sample.spans.append(("forward", BrokenEvent(), BrokenEvent()))
        probe.submit(sample)
        stats = probe.close()
        self.assertEqual(stats["collector_error"], 1)
        self.assertEqual(stats["dropped_collector"], 1)
        self.assertIsNone(probe.begin(1, workload=8))

    def test_unfinished_event_close_exits_without_recycling_slot(self) -> None:
        probe = AsyncProbe(rank=0, case="unfinished", device=0, sink=FullSink(), interval=1, capacity=1)
        sample = probe.begin(0, workload=8)
        sample.spans.append(("forward", NeverReadyEvent(), NeverReadyEvent()))
        probe.submit(sample)
        stats = probe.close(timeout_secs=0.02)
        self.assertFalse(probe.worker.is_alive())
        self.assertEqual(stats["collector_timeout"], 1)
        self.assertEqual(stats["dropped_shutdown"], 1)
        self.assertEqual(len(probe.free), 0)
        self.assertIsNone(probe.begin(1, workload=8))

    def test_training_updates_continue_after_transport_failure(self) -> None:
        sink = SignallingBrokenSink()

        def train(observe: bool) -> torch.Tensor:
            weight = torch.ones(16, device="cuda", requires_grad=True)
            probe = AsyncProbe(rank=0, case="updates", device=0, sink=sink, interval=1) if observe else None
            for step in range(6):
                sample = probe.begin(step, workload=16) if probe else None
                if sample:
                    sample.start("forward")
                loss = (weight * 2).square().mean()
                loss.backward()
                with torch.no_grad():
                    weight -= 0.01 * weight.grad
                weight.grad = None
                if sample:
                    sample.end()
                    probe.submit(sample)
                if observe and step == 0:
                    self.assertTrue(sink.attempted.wait(timeout=2), "failure must precede later training steps")
            torch.cuda.synchronize()
            if probe:
                stats = probe.close()
                self.assertEqual(stats["dropped_sink"], 6)
                self.assertEqual(stats["reported"], 0)
            return weight.detach().cpu()

        self.assertTrue(torch.equal(train(False), train(True)))


if __name__ == "__main__":
    unittest.main()
