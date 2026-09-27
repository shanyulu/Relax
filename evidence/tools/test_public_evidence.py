# Copyright (c) 2026 Relax Authors. All Rights Reserved.

import gzip
import os
import shutil

import pytest
from prepare_public_log import redact
from scan_public_evidence import payload, scan


def test_redaction_preserves_metrics_and_public_addresses():
    private = ".".join(("172", "20", "30", "40"))
    text = f"node={private} loss=0.1393 step=48 remote=8.8.8.8"
    assert redact(text) == "node=[private-address] loss=0.1393 step=48 remote=8.8.8.8"
    assert redact("invalid=999.2.3.4 version=v1.2.3.4") == "invalid=999.2.3.4 version=v1.2.3.4"


@pytest.mark.parametrize("compressed", [False, True])
def test_real_scanner_does_not_skip_log_or_gzip(tmp_path, compressed):
    executable = shutil.which(os.environ.get("GITLEAKS_BIN", "gitleaks"))
    if executable is None:
        pytest.skip("gitleaks executable required for integration test")
    config = tmp_path / "scan.toml"
    config.write_text(
        '[[rules]]\nid="synthetic"\ndescription="synthetic fixture"\nregex="SYNTHETIC_[A-Z]+"\n'
        '[allowlist]\npaths=["\\\\.log$"]\n'
    )
    path = tmp_path / ("raw.log.gz" if compressed else "raw.log")
    body = b"SYNTHETIC_CREDENTIAL\n"
    if compressed:
        with gzip.open(path, "wb") as stream:
            stream.write(body)
    else:
        path.write_bytes(body)
    assert payload(path) == body
    result = scan(path, executable, config)
    assert result["status"] == "BLOCKED"
    assert result["findings"] == [{"rule": "synthetic", "line": 1}]
    assert "CREDENTIAL" not in str(result)
