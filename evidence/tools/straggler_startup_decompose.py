# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Start-up decomposition for the straggler profiler (evidence tool).

Preregistered by evidence/TASK11_STARTUP_DECOMPOSITION.md. Runs out of Ray on
one GPU with the training venv and brackets every bring-up phase of the real
profiler. Writes a JSON phase table to the path given by --out. Measurement
only: this script never patches or edits the profiler.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time

PHASES = []


def _mark(name, t0):
    t = time.perf_counter()
    PHASES.append({"phase": name, "seconds": round(t - t0, 6)})
    return t


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--variant", choices=["local", "collector"], default="local")
    ap.add_argument("--repo", default="/root/autodl-tmp/relax-work/task11-c2")
    args = ap.parse_args()

    sys.path.insert(0, args.repo)

    t0 = time.perf_counter()
    import torch  # noqa: F401

    torch.cuda.set_device(0)
    x = torch.zeros(8, device="cuda")
    torch.cuda.synchronize()
    t0 = _mark("1_cuda_context_ready", t0)

    from relax.utils.straggler import (  # noqa: F401
        StragglerConfig,
        get_straggler_runtime,
        reset_straggler_state_for_tests,
    )

    t0 = _mark("2_import_straggler_modules", t0)

    os.environ["RELAX_STRAGGLER_ENABLE"] = "1"
    os.environ["RELAX_STRAGGLER_OUTPUT_DIR"] = os.path.dirname(os.path.abspath(args.out))
    if args.variant == "collector":
        os.environ["RELAX_STRAGGLER_COLLECTOR_ADDR"] = f"127.0.0.1:{_free_port()}"
    else:
        os.environ.pop("RELAX_STRAGGLER_COLLECTOR_ADDR", None)
    config = StragglerConfig.from_env()
    t0 = _mark("3_config_from_env", t0)

    reset_straggler_state_for_tests()
    runtime = get_straggler_runtime()
    t0 = _mark("4_runtime_start", t0)

    timers = get_straggler_timers = runtime.timers if runtime else None
    if timers is not None:
        for i in range(100):
            timers.start("forward-backward")
            timers.start("forward-compute")
            timers.stop("forward-compute")
            timers.stop("forward-backward")
        t0 = _mark("5_first_100_timer_pairs", t0)
    else:
        PHASES.append({"phase": "5_first_100_timer_pairs", "seconds": None, "error": "no timers"})

    summary = runtime.summary() if runtime else {}
    t0 = _mark("6_summary_report_once_path", t0)

    if runtime is not None:
        runtime.close()
    _mark("7_close_flush", t0)

    payload = {
        "variant": args.variant,
        "repo": args.repo,
        "commit": subprocess.run(
            ["git", "-C", args.repo, "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "collector_addr": os.environ.get("RELAX_STRAGGLER_COLLECTOR_ADDR"),
        "phases": PHASES,
        "summary_keys": sorted(summary.keys())[:32],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(json.dumps(payload["phases"], indent=2))


if __name__ == "__main__":
    main()
