from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import settings
from .exceptions import BadRequestError, ConflictError, InternalError, NotFoundError
from .log_manager import LogManager
from .models import HealthResponse, KillResponse, LogsResponse, ProcessStatus
from .process_manager import ProcessManager
from .tui import run_tui

process_manager = ProcessManager()
log_manager = LogManager(settings.log_dir)
start_time = datetime.now(timezone.utc)
access_logger = logging.getLogger("llm_shell.access")
if not access_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

debug_logger = logging.getLogger("llm_shell.debug")
if not debug_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("DEBUG: %(message)s"))
    debug_logger.addHandler(handler)
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.propagate = False


async def lifespan(app: FastAPI):
    yield
    try:
        current_process = process_manager.get_process()
        if current_process and current_process.poll() is None:
            process_manager.kill("SIGTERM")
    except Exception:
        pass
    log_manager.stop_logging()


app = FastAPI(title="LLM Shell", version="1.0.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Invalid request", "details": exc.errors()})


def _format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"

    if isinstance(seconds, float):
        sec = int(seconds)
    else:
        sec = seconds

    return f"{sec}s"


def _collect_ports(proc: psutil.Process) -> tuple[list[int], int]:
    ports: list[int] = []
    child_count = 0
    try:
        all_connections = proc.connections(kind="all")
    except (psutil.AccessDenied, psutil.Error):
        all_connections = []
    ports.extend(conn.laddr.port for conn in all_connections if conn.laddr)
    try:
        children = proc.children(recursive=True) if proc.is_running() else []
        child_count = len(children)
    except (AttributeError, psutil.Error):
        children = []
    for child in children:
        try:
            child_connections = child.connections(kind="all")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
        ports.extend(conn.laddr.port for conn in child_connections if conn.laddr)
    ports = sorted(set(ports))
    return ports, child_count


def _status_text(payload: dict) -> str:
    lines = []
    lines.append(f"status: {payload.get('status', '-')}")
    lines.append(f"pid: {payload.get('process_pid', '-')}")
    lines.append(f"uptime: {_format_duration(payload.get('uptime_seconds'))}")
    lines.append(f"command: {payload.get('command', '-')}")
    lines.append(f"user: {payload.get('user', '-')}")
    ports = payload.get("ports") or []
    lines.append(f"ports: {','.join(str(p) for p in ports) if ports else '-'}")
    lines.append(f"cpu: {payload.get('cpu_percent', '-')}")
    lines.append(f"mem_mb: {payload.get('memory_mb', '-')}")
    lines.append(f"threads: {payload.get('threads', '-')}")
    lines.append(f"open_files: {payload.get('open_files', '-')}")
    lines.append(f"connections: {payload.get('connections', '-')}")
    lines.append(f"children: {payload.get('children', '-')}")
    lines.append(f"env_count: {payload.get('env_count', '-')}")
    
    # Add log_tail if present (for processes that exit immediately)
    log_tail = payload.get('log_tail')
    if log_tail:
        lines.append(f"\nLogs:\n{log_tail}")
    
    return "\n".join(lines)


def _start_text(payload: dict) -> str:
    return "\n".join(
        [
            f"command: {payload.get('command', '-')}",
            f"status: {payload.get('status', '-')}",
            f"pid: {payload.get('process_pid', '-')}",
            f"created_at: {payload.get('created_at', '-')}",
        ]
    )


def _kill_text(payload: dict) -> str:
    return "\n".join(
        [
            f"status: {payload.get('status', '-')}",
            f"type: {payload.get('type', '-')}",
            f"exit_code: {payload.get('exit_code', '-')}",
            f"stopped_at: {payload.get('stopped_at', '-')}",
        ]
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> dict:
    uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    return {"status": "healthy", "version": "1.0.0", "uptime": uptime}


@app.post("/start", status_code=201)
async def start_process(request: Request, format: str = Query("text")):
    try:
        content_type = request.headers.get("content-type", "")
        command = ""
        if "application/json" in content_type:
            try:
                payload = await request.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                command = str(payload.get("command", "") or "")
        else:
            body = await request.body()
            command = body.decode("utf-8", errors="ignore") if body else("")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid request body") from exc

    if not command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    try:
        access_logger.info("start command=%r", command)
        log_file = log_manager.create_log_file()
        status = process_manager.start(command, log_file)
        log_manager.start_logging(process_manager.get_process(), log_file)
        wait_until = time.monotonic() + 2.0
        while True:
            status = process_manager.get_status()
            if status.get("status") == "exited":
                break
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.05, remaining))
        if status.get("status") == "exited":
            log_manager.stop_logging()  # Ensure log writer completes
            await asyncio.sleep(0.5)  # Give thread time to flush
            try:
                log_tail = log_manager.read_logs(status["log_file"], lines=100).get("content", "")
            except (BadRequestError, NotFoundError):
                log_tail = ""
            status["log_tail"] = log_tail
        if status.get("process_pid") and status.get("status") == "running":
            try:
                proc = psutil.Process(status["process_pid"])
                cpu = proc.cpu_percent(interval=0.0)
                mem = proc.memory_info().rss
                user = proc.username()
                ports, _ = _collect_ports(proc)
                try:
                    open_files = proc.open_files() if proc.is_running() else []
                except (AttributeError, psutil.Error):
                    open_files = []
                try:
                    conns = proc.connections(kind="inet") if proc.is_running() else []
                except (AttributeError, psutil.Error):
                    conns = []
                try:
                    children = proc.children(recursive=True) if proc.is_running() else []
                except (AttributeError, psutil.Error):
                    children = []
                try:
                    env = proc.environ() if proc.is_running() else {}
                except (AttributeError, psutil.Error):
                    env = {}
                uptime_seconds = int(max(0.0, time.time() - proc.create_time()))
                status.update(
                    {
                        "cpu_percent": cpu,
                        "memory_mb": mem / (1024 * 1024),
                        "user": user,
                        "ports": ports,
                        "threads": proc.num_threads(),
                        "open_files": len(open_files),
                        "connections": len(conns),
                        "children": len(children),
                        "env_count": len(env),
                        "env_keys": sorted(list(env.keys()))[:10],
                        "uptime_seconds": uptime_seconds,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                status.update(
                    {
                        "cpu_percent": None,
                        "memory_mb": None,
                        "user": None,
                        "ports": None,
                        "threads": None,
                        "open_files": None,
                        "connections": None,
                        "children": None,
                        "env_count": None,
                        "env_keys": None,
                        "uptime_seconds": None,
                    }
                )
            status.pop("log_file", None)
        if format == "json":
            return status
        return PlainTextResponse(_status_text(status))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InternalError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/status")
async def get_status(format: str = Query("text")):
    try:
        status = process_manager.get_status()
        if status.get("process_pid") and status.get("status") == "running":
            try:
                proc = psutil.Process(status["process_pid"])
                cpu = proc.cpu_percent(interval=0.0)
                mem = proc.memory_info().rss
                user = proc.username()
                ports, _ = _collect_ports(proc)
                try:
                    open_files = proc.open_files() if proc.is_running() else []
                except (AttributeError, psutil.Error):
                    open_files = []
                try:
                    conns = proc.connections(kind="inet") if proc.is_running() else []
                except (AttributeError, psutil.Error):
                    conns = []
                try:
                    children = proc.children(recursive=True) if proc.is_running() else []
                except (AttributeError, psutil.Error):
                    children = []
                try:
                    env = proc.environ() if proc.is_running() else {}
                except (AttributeError, psutil.Error):
                    env = {}
                uptime_seconds = int(max(0.0, time.time() - proc.create_time()))
                status.update(
                    {
                        "cpu_percent": cpu,
                        "memory_mb": mem / (1024 * 1024),
                        "user": user,
                        "ports": ports,
                        "threads": proc.num_threads(),
                        "open_files": len(open_files),
                        "connections": len(conns),
                        "children": len(children),
                        "env_count": len(env),
                        "env_keys": sorted(list(env.keys()))[:10],
                        "uptime_seconds": uptime_seconds,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                status.update(
                    {
                        "cpu_percent": None,
                        "memory_mb": None,
                        "user": None,
                        "ports": None,
                        "threads": None,
                        "open_files": None,
                        "connections": None,
                        "children": None,
                        "env_count": None,
                        "env_keys": None,
                        "uptime_seconds": None,
                    }
                )
            status.pop("log_file", None)
        if format == "json":
            return status
        return PlainTextResponse(_status_text(status))
    except NotFoundError:
        payload = {
            "command": "",
            "status": "not_started",
            "created_at": datetime.now(timezone.utc),
            "process_pid": None,
            "stopped_at": None,
            "exit_code": None,
            "cpu_percent": None,
            "memory_mb": None,
            "user": None,
            "ports": None,
            "threads": None,
            "open_files": None,
            "connections": None,
            "children": None,
            "env_count": None,
            "env_keys": None,
            "uptime_seconds": None,
        }
        if format == "json":
            return payload
        return PlainTextResponse(_status_text(payload))


@app.post("/kill")
async def kill_process(
    type: str = Query("SIGTERM", pattern="^(SIGTERM|SIGKILL)$"),
    format: str = Query("text"),
):
    try:
        result = process_manager.kill(type)
        log_manager.stop_logging()
        if format == "json":
            return result
        return PlainTextResponse(_kill_text(result))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BadRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/restart")
async def restart_process(timeout: int = Query(10, ge=1), format: str = Query("text")):
    try:
        log_manager.stop_logging()
        log_file = log_manager.create_log_file()
        status = process_manager.restart(log_file=log_file, timeout=timeout)
        log_manager.start_logging(process_manager.get_process(), log_file)
        status.pop("log_file", None)
        if format == "json":
            return status
        return PlainTextResponse(_start_text(status))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InternalError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/logs", response_class=PlainTextResponse)
async def get_logs(
    lines: Optional[int] = Query(None, ge=1),
    seconds: Optional[int] = Query(None, ge=1),
) -> PlainTextResponse:
    try:
        status = process_manager.get_status()
        result = log_manager.read_logs(status["log_file"], lines, seconds)
        return PlainTextResponse(result["content"])
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BadRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    if request.headers.get("x-llm-shell-tui") == "1":
        return await call_next(request)

    response = await call_next(request)
    client = request.client.host if request.client else "-"
    access_logger.info("%s %s %s %s", client, request.method, request.url.path, response.status_code)
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Shell API Server")
    parser.add_argument("--host", default=settings.host, help="Host to bind")
    parser.add_argument("--port", type=int, default=settings.port, help="Port to bind")
    parser.add_argument("--tui", action="store_true", help="Run with console UI")
    parser.add_argument("--poll", type=float, default=0.5, help="TUI polling interval (seconds)")
    parser.add_argument("--lines", type=int, default=50, help="TUI app log lines to show")
    parser.add_argument("--access-log", action="store_true", help="Enable uvicorn access log")
    args = parser.parse_args()

    if args.tui:
        run_tui(host=args.host, port=args.port, attach=False, poll=args.poll, lines=args.lines)
        return

    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=args.access_log,
    )


if __name__ == "__main__":
    main()
