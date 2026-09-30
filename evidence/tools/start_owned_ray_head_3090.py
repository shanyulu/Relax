#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Start an owned persistent Ray session with explicitly supplied resources."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ray", type=Path, required=True)
    parser.add_argument("--node-ip", required=True)
    parser.add_argument("--cpus", type=int, required=True)
    parser.add_argument("--gpus", type=int, required=True)
    parser.add_argument("--object-store-memory", type=int, required=True)
    parser.add_argument("--memory", type=int, required=True)
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    command = [
        str(args.ray),
        "start",
        "--head",
        "--block",
        f"--node-ip-address={args.node_ip}",
        "--port=6379",
        "--dashboard-host=127.0.0.1",
        "--dashboard-port=8265",
        f"--num-cpus={args.cpus}",
        f"--num-gpus={args.gpus}",
        f"--object-store-memory={args.object_store_memory}",
        f"--memory={args.memory}",
        f"--temp-dir={args.temp_dir}",
    ]
    env = dict(os.environ)
    for key in (
        "CUDA_VISIBLE_DEVICES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = env["no_proxy"] = "*"
    with (args.out / "bootstrap.log").open("x") as log:
        process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    record = {
        "owner": "codex-task11-parameter-measurement",
        "pid": process.pid,
        "command": command,
        "pgid": os.getpgid(process.pid),
        "sid": os.getsid(process.pid),
        "started_at": time.time(),
        "memory_max_bytes": int(Path("/sys/fs/cgroup/memory.max").read_text()),
        "resource_source": "previous 3090 raylet logs; not copied from the 4090 host",
        "status": "START_REQUESTED; run repository preflight before GPU submission",
    }
    (args.out / "ownership.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
