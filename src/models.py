from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    command: str = Field(..., description="Shell command to run")


class ProcessStatus(BaseModel):
    command: str
    status: Literal["running", "exited", "killed"]
    created_at: datetime
    process_pid: Optional[int]
    log_file: str
    stopped_at: Optional[datetime] = None
    exit_code: Optional[int] = None


class KillResponse(BaseModel):
    stopped_at: datetime
    exit_code: int
    type: Literal["SIGTERM", "SIGKILL"]
    status: Literal["killed"]


class LogsResponse(BaseModel):
    log_file: str
    total_lines: int
    lines_returned: int
    content: str


class HealthResponse(BaseModel):
    status: Literal["healthy"]
    version: str
    uptime: int
