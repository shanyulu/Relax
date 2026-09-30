# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Archive scanned immutable inputs and recompute the frozen overlap
verdict."""

import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    repo = root.parents[3]
    scan_path = root / "TRACE_SCAN_REPORT_20260930.json"
    scan = json.loads(scan_path.read_text())
    assert scan["verdict"] == "PASS" and len(scan["records"]) == 32
    scanned = {row["raw_sha256"] for row in scan["records"] if row["status"] == "PASS"}
    assert len(scanned) == 32
    audit = Path(tempfile.mkdtemp(prefix="task11-overlap-archive-audit-"))
    archives = root / "archives"
    archives.mkdir(exist_ok=True)
    records = []
    for phase, config_name in [("calibration", "O_FREEZE_CONFIG.json"), ("measurement", "O_MEASUREMENT_CONFIG.json")]:
        config = json.loads((root / config_name).read_text())
        seen = set()
        for arm in config["arms"]:
            arm_id = arm["id"]
            arm_dir = root / phase / arm_id
            assert sha256(arm_dir / "manifest.json") == config["arm_manifest_sha256"][arm_id]
            files = [arm_dir / "manifest.json", *sorted((arm_dir / "train_trace").glob("*.gz"))]
            assert len(files) == 5
            members = []
            for path in files:
                name = path.relative_to(root / phase).as_posix()
                digest = sha256(path)
                if path.suffix == ".gz":
                    assert digest == config["raw_trace_hashes"][name] and digest in scanned
                    seen.add(name)
                members.append({"path": name, "sha256": digest, "bytes": path.stat().st_size})
            archive_path = archives / (arm_id + ".tar.gz")
            with (
                archive_path.open("xb") as target,
                gzip.GzipFile(fileobj=target, mode="wb", mtime=0, filename="") as compressed,
            ):
                with tarfile.open(fileobj=compressed, mode="w") as tar:
                    for path in files:
                        info = tar.gettarinfo(str(path), path.relative_to(root / phase).as_posix())
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mode = 0o644
                        with path.open("rb") as source:
                            tar.addfile(info, source)
            unpacked = audit / phase
            unpacked.mkdir(exist_ok=True)
            with tarfile.open(archive_path) as tar:
                tar.extractall(unpacked, filter="data")
            for member in members:
                assert sha256(unpacked / member["path"]) == member["sha256"]
            records.append(
                {
                    "path": archive_path.relative_to(root).as_posix(),
                    "sha256": sha256(archive_path),
                    "bytes": archive_path.stat().st_size,
                    "members": members,
                }
            )
        assert seen == set(config["raw_trace_hashes"])
    analyzer = repo / "evidence/tools/trace_verdict_927c5de.py"
    calibration = audit / "O_CALIBRATION_RESULT.json"
    measurement = audit / "O_MEASUREMENT_RESULT.json"
    subprocess.run(
        [
            sys.executable,
            str(analyzer),
            "freeze",
            "--config",
            str(root / "O_FREEZE_CONFIG.json"),
            "--raw-root",
            str(audit / "calibration"),
            "--out",
            str(calibration),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(analyzer),
            "compare",
            "--config",
            str(root / "O_MEASUREMENT_CONFIG.json"),
            "--raw-root",
            str(audit / "measurement"),
            "--calibration-result",
            str(calibration),
            "--out",
            str(measurement),
        ],
        check=True,
    )
    for path in (calibration, measurement):
        assert path.read_bytes() == (root / path.name).read_bytes(), path.name
    ledger = {
        "schema": "task11-3090-trace-archive-v1",
        "policy": "scan-passed-as-is-v1",
        "product_sha": "927c5de2f5a8f307cad0c87f2c7eb2b78262334d",
        "archive_count": 8,
        "raw_trace_count": 32,
        "scan_report_sha256": sha256(scan_path),
        "archives": records,
        "recomputation": {
            "verdict": "PASS",
            "byte_identical": True,
            "analyzer_sha256": sha256(analyzer),
            "calibration_sha256": sha256(calibration),
            "measurement_sha256": sha256(measurement),
        },
    }
    (root / "PUBLIC_TRACE_LEDGER_20260930.json").write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"verdict": "PASS", "audit_dir": str(audit), "archive_bytes": sum(r["bytes"] for r in records)}))


if __name__ == "__main__":
    main()
