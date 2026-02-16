import shlex
import sys
import time

import pytest

from src.exceptions import ConflictError
from src.process_manager import ProcessManager


def _python_command(code: str) -> str:
    python = shlex.quote(sys.executable)
    return f"{python} -u -c \"{code}\""


def test_start_and_exit_updates_status(tmp_path):
    manager = ProcessManager()
    log_file = str(tmp_path / "start.log")

    status = manager.start(_python_command("print('hello')"), log_file)
    assert status["status"] == "running"

    time.sleep(0.2)
    status = manager.get_status()
    assert status["status"] == "exited"
    assert status["exit_code"] == 0


def test_cannot_start_when_running(tmp_path):
    manager = ProcessManager()
    log_file = str(tmp_path / "run.log")

    manager.start(_python_command("import time; time.sleep(2)"), log_file)
    with pytest.raises(ConflictError):
        manager.start(_python_command("print('x')"), str(tmp_path / "other.log"))

    manager.kill("SIGKILL")


def test_kill_process(tmp_path):
    manager = ProcessManager()
    log_file = str(tmp_path / "kill.log")

    manager.start(_python_command("import time; time.sleep(5)"), log_file)
    result = manager.kill("SIGTERM")

    assert result["status"] == "killed"
    status = manager.get_status()
    assert status["status"] == "killed"


def test_restart_creates_new_process(tmp_path):
    manager = ProcessManager()
    log_file = str(tmp_path / "first.log")

    manager.start(_python_command("import time; time.sleep(1)"), log_file)
    status = manager.restart(log_file=str(tmp_path / "second.log"), timeout=1)

    assert status["status"] == "running"
    assert status["log_file"].endswith("second.log")
    manager.kill("SIGKILL")
