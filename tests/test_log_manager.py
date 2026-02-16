import json
import time
from pathlib import Path

import pytest

from src.exceptions import BadRequestError, NotFoundError
from src.log_manager import LogManager


def _write_json_lines(file_path: Path, entries: list[dict]) -> None:
    with file_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def test_create_log_file(tmp_path):
    manager = LogManager(log_dir=str(tmp_path))
    log_file = manager.create_log_file()

    assert Path(log_file).exists()


def test_read_logs_all(tmp_path):
    manager = LogManager(log_dir=str(tmp_path))
    log_file = Path(manager.create_log_file())

    entries = [
        {"timestamp": "2026-02-16T03:00:00Z", "line": "first"},
        {"timestamp": "2026-02-16T03:00:01Z", "line": "second"},
    ]
    _write_json_lines(log_file, entries)

    result = manager.read_logs(str(log_file))
    assert result["total_lines"] == 2
    assert "first" in result["content"]


def test_read_logs_lines(tmp_path):
    manager = LogManager(log_dir=str(tmp_path))
    log_file = Path(manager.create_log_file())

    entries = [
        {"timestamp": "2026-02-16T03:00:00Z", "line": "one"},
        {"timestamp": "2026-02-16T03:00:01Z", "line": "two"},
        {"timestamp": "2026-02-16T03:00:02Z", "line": "three"},
    ]
    _write_json_lines(log_file, entries)

    result = manager.read_logs(str(log_file), lines=2)
    assert result["lines_returned"] == 2
    assert "one" not in result["content"]


def test_read_logs_seconds(tmp_path):
    manager = LogManager(log_dir=str(tmp_path))
    log_file = Path(manager.create_log_file())

    now = time.time()
    entries = [
        {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 10)), "line": "old"},
        {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "line": "new"},
    ]
    _write_json_lines(log_file, entries)

    result = manager.read_logs(str(log_file), seconds=5)
    assert "new" in result["content"]
    assert "old" not in result["content"]


def test_read_logs_invalid_parameters(tmp_path):
    manager = LogManager(log_dir=str(tmp_path))
    log_file = Path(manager.create_log_file())

    with pytest.raises(BadRequestError):
        manager.read_logs(str(log_file), lines=1, seconds=1)


def test_read_logs_missing_file(tmp_path):
    manager = LogManager(log_dir=str(tmp_path))

    with pytest.raises(NotFoundError):
        manager.read_logs(str(tmp_path / "missing.log"))
