# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Scan exact text inputs, including .log and decompressed .gz, without path
allowlists.

Reports contain hashes and finding locations, never matched credential values.
Raw files are not changed. A failed or incomplete scan is not publishable.
"""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


MAX_BYTES = 512 * 1024 * 1024


def payload(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("scan input exceeds decompressed size bound")
    data.decode("utf-8")  # Reject unsupported binary data instead of silently skipping it.
    return data


def scan(path, executable, config):
    raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    content = payload(path)
    with tempfile.TemporaryDirectory(prefix="evidence-scan-") as directory:
        report = Path(directory) / "findings.json"
        run = subprocess.run(
            [
                executable,
                "stdin",
                "--redact",
                "--no-banner",
                "--config",
                str(config),
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if run.returncode not in (0, 1):
            raise RuntimeError(f"scanner failed with exit {run.returncode}")
        findings = json.loads(report.read_text()) if report.exists() else []
        if run.returncode == 1 and not findings:
            raise RuntimeError("scanner failed without readable findings")
        return {
            "file": str(path),
            "raw_sha256": raw_hash,
            "scanned_sha256": hashlib.sha256(content).hexdigest(),
            "scanned_bytes": len(content),
            "status": "BLOCKED" if findings else "PASS",
            "findings": [{"rule": row["RuleID"], "line": row["StartLine"]} for row in findings],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--gitleaks", default="gitleaks")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refusing to overwrite a scan report")
    executable = shutil.which(args.gitleaks)
    if not executable:
        parser.error("gitleaks not installed")
    records = []
    for path in args.files:
        try:
            records.append(scan(path, executable, args.config))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            records.append({"file": str(path), "status": "INVALID", "error_type": type(exc).__name__})
    verdict = "PASS" if all(row["status"] == "PASS" for row in records) else "BLOCKED"
    args.out.write_text(
        json.dumps(
            {
                "verdict": verdict,
                "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
                "records": records,
            },
            indent=2,
        )
        + "\n"
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
