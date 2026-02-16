from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .exceptions import BadRequestError, NotFoundError


class LogManager:
    def __init__(self, log_dir: str = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._write_lock = threading.Lock()

    def create_log_file(self) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}.log"
        filepath = self.log_dir / filename
        filepath.touch(exist_ok=False)
        return str(filepath)

    def start_logging(self, process, log_file: str) -> None:
        if process is None:
            return
        self._stop_event.clear()
        self._writer_thread = threading.Thread(
            target=self._log_writer,
            args=(process, log_file),
            daemon=True,
        )
        self._writer_thread.start()

    def stop_logging(self) -> None:
        self._stop_event.set()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1)

    def read_logs(
        self,
        log_file: str,
        lines: Optional[int] = None,
        seconds: Optional[int] = None,
    ) -> dict:
        if lines is not None and seconds is not None:
            raise BadRequestError("Cannot specify both 'lines' and 'seconds'")

        file_path = Path(log_file)
        if not file_path.exists():
            raise NotFoundError(f"Log file not found: {log_file}")

        entries = []
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line.strip())
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

        total_lines = len(entries)

        if seconds is not None:
            cutoff = datetime.utcnow() - timedelta(seconds=seconds)
            filtered = [
                entry
                for entry in entries
                if datetime.fromisoformat(entry["timestamp"].rstrip("Z")) >= cutoff
            ]
        elif lines is not None:
            filtered = entries[-lines:] if lines > 0 else entries
        else:
            filtered = entries

        content = "\n".join(entry.get("line", "") for entry in filtered)

        return {
            "log_file": log_file,
            "total_lines": total_lines,
            "lines_returned": len(filtered),
            "content": content,
        }

    def _log_writer(self, process, log_file: str) -> None:
        try:
            with open(log_file, "a", encoding="utf-8") as handle:
                while not self._stop_event.is_set():
                    line = process.stdout.readline()
                    if not line:
                        if process.poll() is not None:
                            break
                        continue

                    log_entry = {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "line": line.decode("utf-8", errors="replace").rstrip("\n\r"),
                    }
                    with self._write_lock:
                        handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                        handle.flush()
        except Exception as exc:
            print(f"Error writing log: {exc}", file=sys.stderr)
