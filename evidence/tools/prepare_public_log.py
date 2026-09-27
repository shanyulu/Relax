# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Create a separately hashed public log without modifying experiment
inputs."""

import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path

from extract_c2_native import parse_arm


NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),  # gitleaks:allow -- public RFC 1918 network definition
    ipaddress.ip_network("192.168.0.0/16"),  # gitleaks:allow -- public RFC 1918 network definition
)
ADDRESS = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


def redact(text):
    def replace(match):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            return match.group()
        return "[private-address]" if any(address in network for network in NETWORKS) else match.group()

    return ADDRESS.sub(replace, text)


def prepare(source, destination, steps):
    if destination.exists():
        raise ValueError("refusing to overwrite public artifact")
    raw = (source / "job.log").read_bytes()
    public = redact(raw.decode("utf-8")).encode("utf-8")
    before = parse_arm(source, expected_steps=steps)
    if not before.get("native_valid"):
        raise ValueError("source log is not a valid native run")
    destination.mkdir(parents=True)
    (destination / "job.log").write_bytes(public)
    after = parse_arm(destination, expected_steps=steps)
    # 'arm' is a presentation field; all extracted measurement fields must match.
    equal = {k: v for k, v in before.items() if k != "arm"} == {k: v for k, v in after.items() if k != "arm"}
    manifest = {
        "policy": "RFC1918-address-only-v1",
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "public_sha256": hashlib.sha256(public).hexdigest(),
        "native_metrics_equal": equal,
        "status": "SCAN_REQUIRED" if equal else "INVALID",
    }
    (destination / "TRANSFORM.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not equal:
        raise ValueError("public transformation changed measurement extraction")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--steps", type=int, required=True)
    args = parser.parse_args()
    if args.steps <= 0:
        parser.error("steps must be positive")
    prepare(args.source, args.out, args.steps)


if __name__ == "__main__":
    main()
