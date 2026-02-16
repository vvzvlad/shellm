import shlex
import sys
import time

import pytest
from fastapi.testclient import TestClient

from src.main import app


client = TestClient(app)


def _python_command(code: str) -> str:
    python = shlex.quote(sys.executable)
    return f"{python} -u -c \"{code}\""


def _cleanup_running_process() -> None:
    status = client.get("/status")
    if status.status_code == 200 and status.json().get("status") == "running":
        client.post("/kill?type=SIGKILL")


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_full_workflow():
    _cleanup_running_process()
    start_response = client.post(
        "/start",
        json={"command": _python_command("import time; print('hello'); time.sleep(5)")},
    )
    assert start_response.status_code == 201
    data = start_response.json()
    assert data["status"] == "running"

    status_response = client.get("/status")
    assert status_response.status_code == 200

    logs_response = client.get("/logs")
    assert logs_response.status_code == 200

    kill_response = client.post("/kill?type=SIGTERM")
    assert kill_response.status_code == 200
    assert kill_response.json()["status"] == "killed"


def test_start_when_running_conflict():
    _cleanup_running_process()
    start_response = client.post(
        "/start",
        json={"command": _python_command("import time; time.sleep(5)")},
    )
    assert start_response.status_code == 201

    conflict = client.post(
        "/start",
        json={"command": _python_command("print('x')")},
    )
    assert conflict.status_code == 409

    client.post("/kill?type=SIGKILL")


def test_logs_invalid_params():
    _cleanup_running_process()
    start_response = client.post(
        "/start",
        json={"command": _python_command("import time; time.sleep(5)")},
    )
    assert start_response.status_code == 201

    response = client.get("/logs?lines=10&seconds=10")
    assert response.status_code == 400

    client.post("/kill?type=SIGKILL")


def test_restart():
    _cleanup_running_process()
    start_response = client.post(
        "/start",
        json={"command": _python_command("import time; time.sleep(5)")},
    )
    assert start_response.status_code == 201
    log_file = start_response.json()["log_file"]

    restart_response = client.post("/restart?timeout=1")
    assert restart_response.status_code == 200
    new_log_file = restart_response.json()["log_file"]
    assert new_log_file != log_file

    time.sleep(0.2)
    client.post("/kill?type=SIGKILL")
