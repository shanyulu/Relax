#!/usr/bin/env python3
"""Fault-isolate the straggler collector on a live Relax run.

Waits for the run to reach its first logged optimizer step, locates the process
that logged `role=collector` (the rank-0 actor, which owns the TCP receiver and
the detector), waits `--delay` seconds, then either SIGKILLs it or SIGSTOPs it
for `--stop-seconds` and resumes it.

Every decision is written to the output JSON with the log evidence that
justified it, so the report never has to trust this script's memory.

Usage:
    kill_collector.py --log <job.log> --mode kill|stop --delay 75
                      --stop-seconds 30 --out <result.json>
"""

import argparse
import json
import os
import re
import signal
import sys
import time

PREFIX_PID = re.compile(r"\((?:MegatronTrainRayActor|ServeReplica:[^)]*) pid=(\d+)\)")
ROLE = re.compile(r"role=(collector|sender|local)\b")
STEP = re.compile(r"step (\d+):")
ROLE_LINE = re.compile(r"straggler profiler (?:enabled|started):")


def read(path: str) -> str:
    try:
        with open(path, errors="replace") as handle:
            return handle.read()
    except FileNotFoundError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--mode", choices=("kill", "stop"), required=True)
    parser.add_argument("--delay", type=float, default=75.0)
    parser.add_argument("--stop-seconds", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    deadline = time.time() + args.timeout
    result = {
        "log": args.log,
        "mode": args.mode,
        "delay_s": args.delay,
        "collector_pid": None,
        "sender_pids": [],
        "roles": {},
        "first_step_seen_at": None,
        "action_at": None,
        "action_sent": None,
        "steps_before_action": [],
        "target_alive_before": None,
        "target_alive_after": None,
        "resumed_at": None,
        "notes": [],
    }

    first_step_time = None
    collector_pid = None
    acted = False
    while time.time() < deadline and not acted:
        text = read(args.log)
        for line in text.splitlines():
            if ROLE_LINE.search(line):
                role = ROLE.search(line)
                pid = PREFIX_PID.search(line)
                if role and pid:
                    result["roles"][pid.group(1)] = role.group(1)
                    if role.group(1) == "collector":
                        collector_pid = int(pid.group(1))
                    elif role.group(1) == "sender":
                        if int(pid.group(1)) not in result["sender_pids"]:
                            result["sender_pids"].append(int(pid.group(1)))
        steps = [int(m) for m in STEP.findall(text)]
        if steps and first_step_time is None:
            first_step_time = time.time()
            result["first_step_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if first_step_time is not None and collector_pid is not None:
            if time.time() - first_step_time >= args.delay:
                acted = True
                break
        time.sleep(2)

    if collector_pid is None:
        result["notes"].append("collector role never appeared in the log within the timeout")
        result["action_sent"] = False
    elif first_step_time is None:
        result["notes"].append("no optimizer step appeared before the timeout")
        result["action_sent"] = False
    else:
        text = read(args.log)
        result["steps_before_action"] = sorted({int(m) for m in STEP.findall(text)})
        result["collector_pid"] = collector_pid
        try:
            os.kill(collector_pid, 0)
            result["target_alive_before"] = True
        except OSError:
            result["target_alive_before"] = False

        if args.mode == "kill":
            os.kill(collector_pid, signal.SIGKILL)
            result["action_sent"] = "SIGKILL"
        else:
            os.kill(collector_pid, signal.SIGSTOP)
            result["action_sent"] = f"SIGSTOP then SIGCONT after {args.stop_seconds}s"
            time.sleep(args.stop_seconds)
            try:
                os.kill(collector_pid, signal.SIGCONT)
                result["resumed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            except OSError as exc:
                result["notes"].append(f"SIGCONT failed: {exc!r}")
        result["action_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            os.kill(collector_pid, 0)
            result["target_alive_after"] = True
        except OSError:
            result["target_alive_after"] = False

    with open(args.out, "w") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())