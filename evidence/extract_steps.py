#!/usr/bin/env python3
"""Supplement analyze_run.py: extract per-step train metrics from Relax's
actor-tagged `step N: {...}` lines, which analyze_run.py's line-anchored
regex misses because the log prefix removes the line start."""
import json
import re
import sys

STEP = re.compile(r"step (\d+): (\{.*?\})\s*$")
NUMBER = re.compile(r"^[0-9.eE+-]+$")


def main() -> int:
    path = sys.argv[1]
    out = {}
    with open(path, errors="replace") as handle:
        for line in handle:
            m = STEP.search(line)
            if not m:
                continue
            step, body = m.group(1), m.group(2)
            fields = {}
            for key, raw in re.findall(r"'([^']+)': ([^,}]+)", body):
                raw = raw.strip()
                if NUMBER.match(raw):
                    fields[key] = float(raw)
            out[step] = fields
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
