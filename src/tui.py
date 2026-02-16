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
from typing import Deque, Optional


def _read_lines(stream, buffer: Deque[str], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        line = stream.readline()
        if not line:
            time.sleep(0.05)
            continue
        buffer.append(line.rstrip("\n"))


def _get_json(url: str, headers: Optional[dict] = None) -> Optional[dict]:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def _draw_pane(stdscr, y: int, height: int, width: int, title: str, lines: Deque[str]) -> None:
    stdscr.addstr(y, 0, title.ljust(width - 1)[: width - 1], curses.A_REVERSE)
    max_lines = height - 1
    visible = list(lines)[-max_lines:]
    for idx in range(max_lines):
        line = visible[idx] if idx < len(visible) else ""
        stdscr.addstr(y + 1 + idx, 0, line.ljust(width - 1)[: width - 1])


def _run_tui(stdscr, api_lines: Deque[str], app_lines: Deque[str], stop_event: threading.Event) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)

    while not stop_event.is_set():
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        split = height // 2

        _draw_pane(stdscr, 0, split, width, " API SERVER LOGS (q to quit) ", api_lines)
        _draw_pane(stdscr, split, height - split, width, " APP LOGS ", app_lines)

        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            stop_event.set()
            break
        time.sleep(0.1)


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
        while not stop_event.is_set():
            status = _get_json(f"{base_url}/status", headers=headers)
            if status and status.get("log_file"):
                logs = _get_json(f"{base_url}/logs?lines={lines}", headers=headers)
                if logs and logs.get("content"):
                    app_lines.clear()
                    app_lines.extend(logs["content"].splitlines())
                elif logs and logs.get("content") == "":
                    app_lines.clear()
                    app_lines.append("[no logs yet]")
            else:
                app_lines.clear()
                app_lines.append("[process not started]")
            time.sleep(poll)

    threading.Thread(target=poll_app_logs, daemon=True).start()

    try:
        curses.wrapper(_run_tui, api_lines, app_lines, stop_event)
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
