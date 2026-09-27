# Copyright (c) 2026 Relax Authors. All Rights Reserved.

import importlib.util
import signal
import subprocess
from pathlib import Path

import pytest


def load(monkeypatch: pytest.MonkeyPatch):
    path = Path(__file__).with_name("run_postreview_smoke.py")
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("postreview_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_submit_timeout_stops_only_its_own_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load(monkeypatch)
    calls = []

    class Process:
        pid = 987654
        count = 0

        def wait(self, timeout: int) -> int:
            self.count += 1
            if self.count == 1:
                raise subprocess.TimeoutExpired("owned-submit", timeout)
            return 0

    def popen(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        module.submit(["owned-submit"], tmp_path, {}, None)
    assert calls == [(987654, signal.SIGTERM), (987654, signal.SIGKILL)]


def test_successful_submit_does_not_stop_processes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load(monkeypatch)

    class Process:
        def wait(self, timeout: int) -> int:
            return 0

    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: Process())

    def forbidden(*args):
        pytest.fail("successful submission must not stop any process")

    monkeypatch.setattr(module.os, "killpg", forbidden)
    module.submit(["owned-submit"], tmp_path, {}, None)
