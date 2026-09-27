# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""C3 real-slowdown agent: bounded CUDA contention on one GPU.

Deliberately competes for SM time on cuda:3 with a fixed duty cycle, creating
a REAL external slowdown for the rank pinned to that GPU. Owned by the C3
campaign; killed by explicit PID afterwards.
"""
import sys
import time

import torch

gpu = int(sys.argv[1]) if len(sys.argv) > 1 else 3
duty_ms = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
idle_ms = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
torch.cuda.set_device(gpu)
a = torch.randn(2048, 2048, device=f"cuda:{gpu}")
b = torch.randn(2048, 2048, device=f"cuda:{gpu}")
print(f"spinner on cuda:{gpu} duty={duty_ms}ms idle={idle_ms}ms pid={__import__('os').getpid()}", flush=True)
while True:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < duty_ms:
        c = a @ b
    torch.cuda.synchronize(gpu)
    time.sleep(idle_ms / 1000.0)
