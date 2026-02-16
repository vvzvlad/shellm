from __future__ import annotations

import argparse
import curses
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Optional


def _read_lines(stream, buffer: Deque[str], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        line = stream.readline()
        if not line:
            time.sleep(0.05)
            continue
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        buffer.append(f"{timestamp} {line.rstrip('\n')}")


def _get_json(url: str, headers: Optional[dict] = None) -> Optional[dict]:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def _get_text(url: str, headers: Optional[dict] = None) -> Optional[str]:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError:
        return None


def _post_json(url: str, headers: Optional[dict] = None) -> Optional[dict]:
    try:
        request = urllib.request.Request(url, method="POST", headers=headers or {})
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_uptime(created_at: Optional[str]) -> str:
    parsed = _parse_time(created_at)
    if not parsed:
        return "-"
    delta = datetime.now(timezone.utc) - parsed
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "-"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def _format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    if seconds < 0:
        return "-"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def _draw_pane(
    stdscr,
    y: int,
    x: int,
    height: int,
    width: int,
    title: str,
    lines: Deque[str],
) -> None:
    stdscr.addstr(y, x, title.ljust(width - 1)[: width - 1], curses.A_REVERSE)
    max_lines = height - 1
    visible = list(lines)[-max_lines:]
    for idx in range(max_lines):
        line = visible[idx] if idx < len(visible) else ""
        stdscr.addstr(y + 1 + idx, x, line.ljust(width - 1)[: width - 1])


def _wrap_text(text: str, max_width: int) -> list[str]:
    if max_width <= 1:
        return [text]
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _format_bytes(value: Optional[int]) -> str:
    if value is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {units[idx]}"


def _sparkline(values: list[float], max_points: int) -> str:
    if not values:
        return "-"
    levels = "▁▂▃▄▅▆▇█"
    trimmed = values[-max_points:]
    scaled = []
    for value in trimmed:
        clamped = max(0.0, min(100.0, value))
        idx = int(round((clamped / 100.0) * (len(levels) - 1)))
        scaled.append(levels[idx])
    return "".join(scaled)


def _run_tui(stdscr, api_lines: Deque[str], app_lines: Deque[str], status_info: dict, status_lock: threading.Lock, stop_event: threading.Event, kill_term, kill_kill) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)

    try:
        while not stop_event.is_set():
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            split = height // 2
            side_width = max(28, width // 3)
            right_width = max(20, width - side_width)
            right_x = side_width

            with status_lock:
                status = status_info.copy()

            current_status = status.get("status", "-")
            show_runtime = current_status == "running"

            status_lines = deque(maxlen=100)
            label_width = 8
            value_width = 12
            spark_width = max(1, side_width - label_width - value_width - 1)
            def row(label: str, value: str) -> str:
                return f"{label.ljust(label_width)}{value}"

            def row_with_spark(label: str, value: str, history: list[float]) -> str:
                spark = _sparkline(history, spark_width)
                return f"{label.ljust(label_width)}{value.ljust(value_width)}{spark}"

            status_lines.append(row("STATUS", current_status))
            status_lines.append(row("PID", str(status.get('pid', '-') if show_runtime else '-')))
            status_lines.append(row("UPTIME", str(status.get('uptime', '-') if show_runtime else '-')))
            status_lines.append(row("USER", str(status.get('user', '-') if show_runtime else '-')))
            status_lines.append(row("THR", str(status.get('threads', '-') if show_runtime else '-')))
            status_lines.append(row("FILES", str(status.get('open_files', '-') if show_runtime else '-')))
            status_lines.append(row("CONNS", str(status.get('connections', '-') if show_runtime else '-')))
            status_lines.append(row("CHILD", str(status.get('children', '-') if show_runtime else '-')))
            status_lines.append(row("ENV", str(status.get('env_count', '-') if show_runtime else '-')))
            ports = status.get("ports") if show_runtime else None
            status_lines.append(row("PORTS", str(ports if ports else '-')))

            cpu_value = str(status.get('cpu', '-') if show_runtime else '-')
            mem_value = str(status.get('mem', '-') if show_runtime else '-')
            io_value = str(status.get('io_rate', '-') if show_runtime else '-')
            status_lines.append(row_with_spark("CPU", cpu_value, status.get("cpu_history", [])))
            status_lines.append(row_with_spark("MEM", mem_value, status.get("mem_history", [])))
            status_lines.append(row_with_spark("IO", io_value, status.get("io_history", [])))
            status_lines.append("")
            status_lines.append("COMMAND:")
            command = status.get("command", "-") or "-"
            for line in _wrap_text(command, side_width - 2):
                status_lines.append(line)

            wrapped_app_lines = deque()
            wrap_width = max(1, right_width - 2)
            for line in app_lines:
                for wrapped_line in _wrap_text(line, wrap_width):
                    wrapped_app_lines.append(wrapped_line)

            _draw_pane(stdscr, 0, 0, height, side_width, " STATUS ", status_lines)
            _draw_pane(stdscr, 0, right_x, split, right_width, " API SERVER LOGS (q to quit) ", api_lines)
            _draw_pane(stdscr, split, right_x, height - split, right_width, " APP LOGS (k to SIGTERM, K/9 to SIGKILL))", wrapped_app_lines)

            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                stop_event.set()
                break
            if ch == ord("k"):
                kill_term()
            if ch in (ord("K"), ord("9")):
                kill_kill()
            time.sleep(0.1)
    except KeyboardInterrupt:
        stop_event.set()
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Shell TUI")
    parser.add_argument("--host", default="127.0.0.1", help="API host")
    parser.add_argument("--port", type=int, default=8000, help="API port")
    parser.add_argument("--attach", action="store_true", help="Attach to existing API server")
    parser.add_argument("--poll", type=float, default=0.5, help="Polling interval (seconds)")
    parser.add_argument("--lines", type=int, default=50, help="Number of app log lines to show")
    args = parser.parse_args()

    run_tui(
        host=args.host,
        port=args.port,
        attach=args.attach,
        poll=args.poll,
        lines=args.lines,
    )


def run_tui(host: str, port: int, attach: bool, poll: float, lines: int) -> None:
    api_lines: Deque[str] = deque(maxlen=500)
    app_lines: Deque[str] = deque(maxlen=500)
    stop_event = threading.Event()
    status_lock = threading.Lock()
    status_info = {
        "status": "-",
        "pid": "-",
        "command": "-",
        "uptime": "-",
        "cpu": "-",
        "mem": "-",
        "user": "-",
        "ports": "-",
    }
    last_status: Optional[str] = None
    cpu_history: Deque[float] = deque(maxlen=400)
    mem_history: Deque[float] = deque(maxlen=400)
    io_history: Deque[float] = deque(maxlen=400)
    last_io_total: Optional[int] = None
    last_io_time: Optional[float] = None

    api_process: Optional[subprocess.Popen] = None
    if not attach:
        api_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.main",
                "--host",
                host,
                "--port",
                str(port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        threading.Thread(
            target=_read_lines,
            args=(api_process.stdout, api_lines, stop_event),
            daemon=True,
        ).start()
    else:
        api_lines.append("[attach] API server logs are not captured in attach mode")

    def poll_app_logs() -> None:
        base_url = f"http://{host}:{port}"
        headers = {"x-llm-shell-tui": "1"}
        nonlocal last_status, last_io_total, last_io_time
        while not stop_event.is_set():
            status = _get_json(f"{base_url}/status?format=json", headers=headers)
            if status:
                with status_lock:
                    status_info["status"] = status.get("status") or "-"
                    status_info["pid"] = status.get("process_pid") or "-"
                    status_info["command"] = status.get("command") or "-"
                    uptime_seconds = status.get("uptime_seconds")
                    status_info["uptime"] = _format_duration(uptime_seconds)
                    cpu = status.get("cpu_percent")
                    mem = status.get("memory_mb")
                    status_info["cpu"] = f"{cpu:.1f}%" if isinstance(cpu, (int, float)) else "-"
                    status_info["mem"] = f"{mem:.1f} MB" if isinstance(mem, (int, float)) else "-"
                    status_info["user"] = status.get("user") or "-"
                    status_info["threads"] = status.get("threads")
                    status_info["open_files"] = status.get("open_files")
                    status_info["connections"] = status.get("connections")
                    status_info["children"] = status.get("children")
                    status_info["env_count"] = status.get("env_count")
                    ports = status.get("ports")
                    status_info["ports"] = ",".join(str(p) for p in ports) if ports else "-"
                    read_bytes = status.get("io_read_bytes")
                    write_bytes = status.get("io_write_bytes")
                    now = time.time()
                    if isinstance(read_bytes, int) and isinstance(write_bytes, int):
                        total = read_bytes + write_bytes
                        if last_io_total is not None and last_io_time is not None:
                            delta_bytes = max(0, total - last_io_total)
                            delta_time = max(0.001, now - last_io_time)
                            rate = delta_bytes / delta_time
                            status_info["io_rate"] = f"{_format_bytes(int(rate))}/s"
                            io_history.append(min(100.0, rate / (1024 * 1024) * 10))
                        last_io_total = total
                        last_io_time = now
                    status_info["io_history"] = list(io_history)
                    if isinstance(cpu, (int, float)):
                        cpu_history.append(float(cpu))
                    if isinstance(mem, (int, float)):
                        mem_history.append(float(mem))
                    status_info["cpu_history"] = list(cpu_history)
                    status_info["mem_history"] = list(mem_history)

                current_status = status.get("status")
                if last_status == "running" and current_status in {"exited", "killed"}:
                    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    api_lines.append(f"{timestamp} status changed: running -> {current_status}")
                last_status = current_status

            if status and status.get("log_file"):
                logs_text = _get_text(f"{base_url}/logs?lines={lines}", headers=headers)
                if logs_text is not None:
                    app_lines.clear()
                    if logs_text.strip():
                        app_lines.extend(logs_text.splitlines())
                    else:
                        app_lines.append("[no logs yet]")
            else:
                app_lines.clear()
                app_lines.append("[process not started]")
            time.sleep(poll)

    def kill_term() -> None:
        base_url = f"http://{host}:{port}"
        headers = {"x-llm-shell-tui": "1"}
        _post_json(f"{base_url}/kill?type=SIGTERM", headers=headers)

    def kill_kill() -> None:
        base_url = f"http://{host}:{port}"
        headers = {"x-llm-shell-tui": "1"}
        _post_json(f"{base_url}/kill?type=SIGKILL", headers=headers)

    threading.Thread(target=poll_app_logs, daemon=True).start()

    try:
        curses.wrapper(_run_tui, api_lines, app_lines, status_info, status_lock, stop_event, kill_term, kill_kill)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        if api_process and api_process.poll() is None:
            api_process.terminate()
            try:
                api_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                api_process.kill()


if __name__ == "__main__":
    main()
