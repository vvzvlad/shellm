# LLM Shell

HTTP API for managing a single process in a non-blocking mode. It is suitable for LLM agents to запускать servers/tests, view logs, and restart processes without blocking the console.

## Quick Start

```bash
pip install -r requirements.txt
python -m src.main --port 8000
```

Check:

```bash
curl http://localhost:8000/health
```

## API

### POST /start

```bash
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "python -m http.server 8080"}'
```

By default, responses are plain text. For JSON, add `?format=json`.

### GET /status

```bash
curl http://localhost:8000/status
```

For JSON: `curl 'http://localhost:8000/status?format=json'`.

### POST /kill

```bash
curl -X POST 'http://localhost:8000/kill?type=SIGTERM'
```

For JSON: `curl -X POST 'http://localhost:8000/kill?type=SIGTERM&format=json'`.

### POST /restart

```bash
curl -X POST 'http://localhost:8000/restart?timeout=5'
```

For JSON: `curl -X POST 'http://localhost:8000/restart?timeout=5&format=json'`.

### GET /logs

```bash
curl 'http://localhost:8000/logs?lines=100'
curl 'http://localhost:8000/logs?seconds=30'
```

## Configuration

You can configure via ENV:

```bash
export LLM_SHELL_PORT=8000
export LLM_SHELL_HOST=0.0.0.0
```

Or via CLI:

```bash
python -m src.main --host 127.0.0.1 --port 8000
```

## Tests

```bash
pytest -v
```

## TUI (split console into two panes)

Run the server in TUI mode (single command):

```bash
python -m src.main --tui
```

The bottom pane shows status (state, pid, uptime), the command, and hotkeys:
- `k` — SIGTERM
- `K` or `9` — SIGKILL

Additionally, the status shows process metrics (CPU/RAM/ports/user) via `psutil`.

Settings:
- `--host` and `--port` — API address
- `--poll` — log polling frequency
- `--lines` — how many log lines to show
- `--access-log` — enable uvicorn access log (disabled by default; TUI polling is hidden via a header)

## Features

- Only one process at a time
- Logs are written to `logs/` in JSON format
- `shell=True` to support `cd`, variables, and pipes
- `lines` and `seconds` cannot be used together
