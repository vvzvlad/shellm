from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Optional

from .exceptions import BadRequestError, ConflictError, InternalError, NotFoundError


class ProcessManager:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._command: Optional[str] = None
        self._created_at: Optional[datetime] = None
        self._log_file: Optional[str] = None
        self._stopped_at: Optional[datetime] = None
        self._exit_code: Optional[int] = None
        self._status_override: Optional[str] = None

    def start(self, command: str, log_file: str) -> dict:
        self._update_status()
        if self.is_running():
            raise ConflictError("Process already running")

        self._command = command
        self._created_at = datetime.now(timezone.utc)
        self._log_file = log_file
        self._stopped_at = None
        self._exit_code = None
        self._status_override = None

        try:
            self._process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            )
        except Exception as exc:
            raise InternalError(f"Failed to start process: {exc}") from exc

        return self._get_status_dict()

    def get_status(self) -> dict:
        if self._process is None:
            raise NotFoundError("No process started")

        self._update_status()
        return self._get_status_dict()

    def get_process(self) -> Optional[subprocess.Popen]:
        return self._process

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def kill(self, signal_type: str) -> dict:
        if self._process is None:
            raise NotFoundError("No process to kill")

        self._update_status()
        if not self.is_running():
            raise BadRequestError("Process already exited")

        if signal_type == "SIGTERM":
            self._process.terminate()
        elif signal_type == "SIGKILL":
            self._process.kill()
        else:
            raise BadRequestError(f"Invalid signal type: {signal_type}")

        try:
            exit_code = self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if signal_type == "SIGTERM":
                self._process.kill()
                exit_code = self._process.wait()
            else:
                exit_code = self._process.wait()

        self._exit_code = exit_code
        self._stopped_at = datetime.now(timezone.utc)
        self._status_override = "killed"

        return {
            "stopped_at": self._stopped_at,
            "exit_code": exit_code,
            "type": signal_type,
            "status": "killed",
        }

    def restart(self, log_file: str, timeout: int = 10) -> dict:
        if self._process is None or self._command is None:
            raise NotFoundError("No process to restart")

        self._update_status()
        if self.is_running():
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()

        return self.start(self._command, log_file)

    def set_log_file(self, log_file: str) -> None:
        self._log_file = log_file

    def _update_status(self) -> None:
        if self._process is None:
            return

        exit_code = self._process.poll()
        if exit_code is not None and self._exit_code is None:
            self._exit_code = exit_code
            self._stopped_at = datetime.now(timezone.utc)

    def _get_status_dict(self) -> dict:
        if self._status_override == "killed":
            status = "killed"
        elif self._process is None and self._command is None:
            status = "not_started"
        else:
            status = "running" if self.is_running() else "exited"

        return {
            "command": self._command or "",
            "status": status,
            "created_at": self._created_at or datetime.now(timezone.utc),
            "process_pid": self._process.pid if self._process else None,
            "log_file": self._log_file or "",
            "stopped_at": self._stopped_at,
            "exit_code": self._exit_code,
        }
