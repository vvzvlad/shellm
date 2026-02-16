---
name: llm-shell-operator
description: This skill should be used when an agent needs to operate the local LLM Shell HTTP API to start/stop processes, poll status, and read logs during iterative development.
---

# LLM Shell Operator Skill

## Purpose

Provide a repeatable workflow for controlling the LLM Shell API: start a process, confirm it is running, read logs, restart or kill it, and validate with tests.

## When to Use

- Need to start a long-running server without blocking the agent console.
- Need to read logs from a running process or after a failure.
- Need to restart a process after code changes.
- Need to kill a process cleanly or forcefully.

## Output formats

- `/start`, `/status`, `/kill`, `/restart` return **plain text** by default, add `?format=json` to get JSON for machine parsing.
- `/logs` always returns **plain text**.
- `/start` accepts either JSON (`{"command": "..."}`) or a raw plain-text body with the command string. It is preferable to use plain text body

## Testing methodology (required)

- Use the `execute_command` tool with `curl` for all testing or interaction with llm_shell API endpoints.
- Do **not** use a browser to test API endpoints.

## Repeating check
If you need to periodically check a process, do not execute `curl -s ‘http://localhost:8776/logs’` repeatedly, as too frequent and rapid requests of the same command will cause the agent to freeze.

Instead, use `sleep 20 && curl -s ‘http://localhost:8776/logs’`, setting the desired time instead of 20 if you think it should be different. But as a rule, 20 seconds is a good time for almost any application.


## Project command preface (required)

- ALWAYS change to the project directory before running the server or executing any commands for this project: `cd /Users/vvzvlad/projects/example_dir`.
- If the project is in Python, ALWAYS activate the virtual environment before running the server or executing any commands for this project: `source venv/bin/activate`.
- Example command format:

```bash
cd /Users/vvzvlad/projects/example_dir && source .venv/bin/activate && python -m example_app.py
```
Instead of /Users/vvzvlad/projects/server_hd, you should substitute the directory where you want to run your project.


Example `curl` commands (use via `execute_command`):

```bash
curl -s http://localhost:8776/health
```

```bash
curl -s -X POST http://localhost:8776/start \
  -H "Content-Type: application/json" \
  -d '{"command":"python -m http.server 8080"}'
```

```bash
curl -s http://localhost:8776/status
```

```bash
curl -s -X POST 'http://localhost:8776/kill?type=SIGTERM'
```

## Workflow

### 1) Check API health

Run:

```bash
curl -s http://localhost:8776/health
```

Expect `{"status":"healthy"}`.

### 2) Start a process

- JSON body:

```bash
curl -s -X POST http://localhost:8776/start \
  -H "Content-Type: application/json" \
  -d '{"command":"python -m http.server 8080"}'
```

- Plain-text body (no JSON):

```bash
curl -s -X POST http://localhost:8776/start \
  -H "Content-Type: text/plain" \
  -d 'python -m http.server 8080'
```

Note (EN): after POST /start (run_command), the API waits ~2 seconds before responding to collect PID/status and catch early errors (e.g., invalid folder paths).
Look closely at the API response to see if the command actually ran.

JSON response:

```bash
curl -s -X POST 'http://localhost:8776/start?format=json' \
  -H "Content-Type: application/json" \
  -d '{"command":"python -m http.server 8080"}'
```

If response is 409, process is already running. Decide to kill it first or restart.

### 3) Check status

Plain text:

```bash
curl -s http://localhost:8776/status
```

JSON:

```bash
curl -s 'http://localhost:8776/status?format=json'
```

If `status` is `running`, continue. If `exited`, inspect logs.

### 4) Read logs

- Last N lines:

```bash
curl -s 'http://localhost:8776/logs?lines=100'
```

- Last N seconds:

```bash
curl -s 'http://localhost:8776/logs?seconds=30'
```

Do not pass both `lines` and `seconds` in one request.

### 5) Restart after code changes

Plain text:

```bash
curl -s -X POST 'http://localhost:8776/restart?timeout=5'
```

JSON:

```bash
curl -s -X POST 'http://localhost:8776/restart?timeout=5&format=json'
```

This sends SIGTERM first, then SIGKILL if the process does not exit within timeout.

### 6) Kill process

Plain text:

```bash
curl -s -X POST 'http://localhost:8776/kill?type=SIGTERM'
```

JSON:

```bash
curl -s -X POST 'http://localhost:8776/kill?type=SIGTERM&format=json'
```

### 7) Example loop command

Run a looping command to validate log streaming:

```bash
curl -s -X POST http://localhost:8776/start \
  -H "Content-Type: application/json" \
  -d '{"command":"while true; do echo loop-$(date +%H:%M:%S); sleep 1; done"}'
```
Then:

```bash
curl -s 'http://localhost:8776/logs?lines=5'
```

### 8) Typical dev cycle

1. Start server via `/start`.
2. Run tests in separate command.
3. If tests fail, fetch logs via `/logs`.
4. Fix code.
5. `/restart` the process.
6. Re-run tests.
7. `/kill` when done.

## Error Handling

- 400: invalid request (empty command, lines+seconds, bad params)
- 404: process not started or log file missing
- 409: process already running
- 500: internal error

## Notes

- Single session only: cannot run multiple processes at once.
- Commands run via shell, so `cd` and env vars are supported: `"cd app && PORT=8080 python server.py"`.
- Logs are stored in `logs/` as JSON lines; `/logs` returns plain text.
