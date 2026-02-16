from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .exceptions import BadRequestError, ConflictError, InternalError, NotFoundError
from .log_manager import LogManager
from .models import HealthResponse, KillResponse, LogsResponse, ProcessStatus, StartRequest
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


@app.get("/health", response_model=HealthResponse)
async def health_check() -> dict:
    uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    return {"status": "healthy", "version": "1.0.0", "uptime": uptime}


@app.post("/start", status_code=201, response_model=ProcessStatus)
async def start_process(request: StartRequest) -> dict:
    if not request.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    try:
        access_logger.info("start command=%r", request.command)
        log_file = log_manager.create_log_file()
        status = process_manager.start(request.command, log_file)
        log_manager.start_logging(process_manager.get_process(), log_file)
        return status
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InternalError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/status", response_model=ProcessStatus)
async def get_status() -> dict:
    try:
        return process_manager.get_status()
    except NotFoundError:
        return {
            "command": "",
            "status": "exited",
            "created_at": datetime.now(timezone.utc),
            "process_pid": None,
            "log_file": "",
            "stopped_at": None,
            "exit_code": None,
        }


@app.post("/kill", response_model=KillResponse)
async def kill_process(type: str = Query("SIGTERM", pattern="^(SIGTERM|SIGKILL)$")) -> dict:
    try:
        result = process_manager.kill(type)
        log_manager.stop_logging()
        return result
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BadRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/restart", response_model=ProcessStatus)
async def restart_process(timeout: int = Query(10, ge=1)) -> dict:
    try:
        log_manager.stop_logging()
        log_file = log_manager.create_log_file()
        status = process_manager.restart(log_file=log_file, timeout=timeout)
        log_manager.start_logging(process_manager.get_process(), log_file)
        return status
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InternalError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/logs", response_model=LogsResponse)
async def get_logs(
    lines: Optional[int] = Query(None, ge=1),
    seconds: Optional[int] = Query(None, ge=1),
) -> dict:
    try:
        status = process_manager.get_status()
        return log_manager.read_logs(status["log_file"], lines, seconds)
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
