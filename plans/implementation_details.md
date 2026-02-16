# Детали реализации

## ProcessManager - детальная спецификация

### Структура класса

```python
class ProcessManager:
    def __init__(self):
        self._process: Optional[Popen] = None
        self._command: Optional[str] = None
        self._created_at: Optional[datetime] = None
        self._log_file: Optional[str] = None
        self._stopped_at: Optional[datetime] = None
        self._exit_code: Optional[int] = None
        
    def start(self, command: str, log_file: str) -> dict
    def get_status(self) -> dict
    def kill(self, signal_type: str) -> dict
    def restart(self, timeout: int = 10) -> dict
    def _update_status(self) -> None
```

### Метод start()

```python
def start(self, command: str, log_file: str) -> dict:
    # 1. Проверка: есть ли уже процесс
    self._update_status()
    if self._process is not None and self._process.poll() is None:
        raise ConflictError("Process already running")
    
    # 2. Запуск нового процесса
    self._command = command
    self._created_at = datetime.utcnow()
    self._log_file = log_file
    self._stopped_at = None
    self._exit_code = None
    
    try:
        self._process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,  # Line buffered
            universal_newlines=False  # Bytes mode
        )
    except Exception as e:
        raise InternalError(f"Failed to start process: {e}")
    
    # 3. Возврат статуса
    return self._get_status_dict()
```

### Метод get_status()

```python
def get_status(self) -> dict:
    if self._process is None:
        raise NotFoundError("No process started")
    
    self._update_status()
    return self._get_status_dict()
```

### Метод _update_status()

```python
def _update_status(self) -> None:
    """Проверяет статус процесса через poll()"""
    if self._process is None:
        return
    
    exit_code = self._process.poll()
    if exit_code is not None and self._exit_code is None:
        # Процесс завершился
        self._exit_code = exit_code
        self._stopped_at = datetime.utcnow()
```

### Метод kill()

```python
def kill(self, signal_type: str) -> dict:
    if self._process is None:
        raise NotFoundError("No process to kill")
    
    self._update_status()
    if self._process.poll() is not None:
        raise BadRequestError("Process already exited")
    
    if signal_type == "SIGTERM":
        self._process.terminate()  # Sends SIGTERM
    elif signal_type == "SIGKILL":
        self._process.kill()  # Sends SIGKILL
    else:
        raise BadRequestError(f"Invalid signal type: {signal_type}")
    
    # Ждем завершения
    try:
        exit_code = self._process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Force kill if still alive after SIGTERM
        if signal_type == "SIGTERM":
            self._process.kill()
            exit_code = self._process.wait()
    
    self._exit_code = exit_code
    self._stopped_at = datetime.utcnow()
    
    return {
        "stopped_at": self._stopped_at,
        "exit_code": exit_code,
        "type": signal_type,
        "status": "killed"
    }
```

### Метод restart()

```python
def restart(self, timeout: int = 10) -> dict:
    if self._process is None or self._command is None:
        raise NotFoundError("No process to restart")
    
    old_command = self._command
    
    # 1. Попытка graceful shutdown
    self._update_status()
    if self._process.poll() is None:  # Still running
        self._process.terminate()  # SIGTERM
        
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Force kill
            self._process.kill()
            self._process.wait()
    
    # 2. Создание нового лог-файла
    from .log_manager import LogManager
    log_manager = LogManager()
    new_log_file = log_manager.create_log_file()
    
    # 3. Запуск нового процесса
    return self.start(old_command, new_log_file)
```

## LogManager - детальная спецификация

### Структура класса

```python
class LogManager:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._write_lock = threading.Lock()
        
    def create_log_file(self) -> str
    def start_logging(self, process: Popen, log_file: str) -> None
    def stop_logging(self) -> None
    def read_logs(self, log_file: str, lines: Optional[int], seconds: Optional[int]) -> dict
    def _log_writer(self, process: Popen, log_file: str) -> None
```

### Метод create_log_file()

```python
def create_log_file(self) -> str:
    """Создает имя нового лог-файла"""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.log"
    filepath = self.log_dir / filename
    
    # Создаем пустой файл
    filepath.touch()
    
    return str(filepath)
```

### Метод start_logging()

```python
def start_logging(self, process: Popen, log_file: str) -> None:
    """Запускает поток для записи логов"""
    self._stop_event.clear()
    self._writer_thread = threading.Thread(
        target=self._log_writer,
        args=(process, log_file),
        daemon=True
    )
    self._writer_thread.start()
```

### Метод _log_writer()

```python
def _log_writer(self, process: Popen, log_file: str) -> None:
    """Worker thread для записи логов в реальном времени"""
    with open(log_file, 'a', encoding='utf-8') as f:
        while not self._stop_event.is_set():
            # Читаем с небольшим таймаутом
            try:
                line = process.stdout.readline()
                if not line:
                    # EOF - процесс завершился
                    if process.poll() is not None:
                        break
                    continue
                
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + 'Z',
                    "line": line.decode('utf-8').rstrip('\n\r')
                }
                
                with self._write_lock:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                    f.flush()
                    
            except Exception as e:
                # Логируем ошибку но продолжаем
                print(f"Error writing log: {e}", file=sys.stderr)
```

### Метод read_logs()

```python
def read_logs(
    self, 
    log_file: str, 
    lines: Optional[int] = None, 
    seconds: Optional[int] = None
) -> dict:
    """Читает и фильтрует логи"""
    
    # Валидация
    if lines is not None and seconds is not None:
        raise BadRequestError("Cannot specify both 'lines' and 'seconds'")
    
    if not Path(log_file).exists():
        raise NotFoundError(f"Log file not found: {log_file}")
    
    # Читаем все строки
    all_entries = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                all_entries.append(entry)
            except json.JSONDecodeError:
                # Пропускаем поврежденные строки
                continue
    
    total_lines = len(all_entries)
    
    # Фильтрация
    if seconds is not None:
        cutoff_time = datetime.utcnow() - timedelta(seconds=seconds)
        filtered = [
            e for e in all_entries
            if datetime.fromisoformat(e['timestamp'].rstrip('Z')) >= cutoff_time
        ]
    elif lines is not None:
        filtered = all_entries[-lines:] if lines > 0 else all_entries
    else:
        filtered = all_entries
    
    # Конвертация в plain text
    content = '\n'.join(e['line'] for e in filtered)
    
    return {
        "log_file": log_file,
        "total_lines": total_lines,
        "lines_returned": len(filtered),
        "content": content
    }
```

## FastAPI приложение - детальная спецификация

### Глобальные объекты

```python
app = FastAPI(title="LLM Shell", version="1.0.0")

process_manager = ProcessManager()
log_manager = LogManager()

# Для uptime
start_time = datetime.utcnow()
```

### Endpoint: POST /start

```python
@app.post("/start", status_code=201, response_model=ProcessStatus)
async def start_process(request: StartRequest):
    """Запускает новый процесс"""
    
    if not request.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty")
    
    try:
        # Создаем лог-файл
        log_file = log_manager.create_log_file()
        
        # Запускаем процесс
        status = process_manager.start(request.command, log_file)
        
        # Начинаем логирование
        log_manager.start_logging(process_manager._process, log_file)
        
        return status
        
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Endpoint: GET /status

```python
@app.get("/status", response_model=ProcessStatus)
async def get_status():
    """Получает статус процесса"""
    
    try:
        return process_manager.get_status()
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

### Endpoint: POST /kill

```python
@app.post("/kill", response_model=KillResponse)
async def kill_process(type: Literal["SIGTERM", "SIGKILL"] = "SIGTERM"):
    """Убивает процесс"""
    
    try:
        result = process_manager.kill(type)
        log_manager.stop_logging()
        return result
        
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Endpoint: POST /restart

```python
@app.post("/restart", response_model=ProcessStatus)
async def restart_process(timeout: int = 10):
    """Перезапускает процесс"""
    
    try:
        # Останавливаем логирование
        log_manager.stop_logging()
        
        # Перезапускаем
        status = process_manager.restart(timeout)
        
        # Начинаем новое логирование
        log_manager.start_logging(process_manager._process, status['log_file'])
        
        return status
        
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Endpoint: GET /logs

```python
@app.get("/logs", response_model=LogsResponse)
async def get_logs(
    lines: Optional[int] = None,
    seconds: Optional[int] = None
):
    """Получает логи процесса"""
    
    try:
        status = process_manager.get_status()
        log_file = status['log_file']
        
        return log_manager.read_logs(log_file, lines, seconds)
        
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BadRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Endpoint: GET /health

```python
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    
    uptime = int((datetime.utcnow() - start_time).total_seconds())
    
    return {
        "status": "healthy",
        "version": "1.0.0",
        "uptime": uptime
    }
```

### Lifecycle events

```python
@app.on_event("startup")
async def startup_event():
    """При старте приложения"""
    logger.info("LLM Shell API starting...")

@app.on_event("shutdown")
async def shutdown_event():
    """При остановке приложения - graceful shutdown процесса"""
    logger.info("LLM Shell API shutting down...")
    
    try:
        if process_manager._process and process_manager._process.poll() is None:
            logger.info("Stopping running process...")
            process_manager.kill("SIGTERM")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    
    log_manager.stop_logging()
```

## Конфигурация

### config.py

```python
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Logging
    log_dir: str = "logs"
    
    # Process
    default_restart_timeout: int = 10
    
    class Config:
        env_prefix = "LLM_SHELL_"
        env_file = ".env"

settings = Settings()
```

### main.py - Entry point

```python
import uvicorn
import argparse
from .config import settings

def main():
    parser = argparse.ArgumentParser(description="LLM Shell API Server")
    parser.add_argument("--host", default=settings.host, help="Host to bind")
    parser.add_argument("--port", type=int, default=settings.port, help="Port to bind")
    
    args = parser.parse_args()
    
    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        log_level="info"
    )

if __name__ == "__main__":
    main()
```

## Исключения (exceptions.py)

```python
class LLMShellError(Exception):
    """Базовое исключение"""
    pass

class ConflictError(LLMShellError):
    """409 - конфликт состояния"""
    pass

class NotFoundError(LLMShellError):
    """404 - ресурс не найден"""
    pass

class BadRequestError(LLMShellError):
    """400 - некорректный запрос"""
    pass

class InternalError(LLMShellError):
    """500 - внутренняя ошибка"""
    pass
```

## Тестирование - примеры

### test_process_manager.py

```python
def test_start_simple_command():
    pm = ProcessManager()
    log_file = "logs/test.log"
    
    result = pm.start("echo 'Hello World'", log_file)
    
    assert result['command'] == "echo 'Hello World'"
    assert result['status'] == 'running'
    assert result['process_pid'] is not None
    
    # Ждем завершения
    time.sleep(0.5)
    status = pm.get_status()
    assert status['status'] == 'exited'
    assert status['exit_code'] == 0

def test_cannot_start_twice():
    pm = ProcessManager()
    pm.start("sleep 10", "logs/test.log")
    
    with pytest.raises(ConflictError):
        pm.start("echo test", "logs/test2.log")
    
    pm.kill("SIGKILL")

def test_restart_process():
    pm = ProcessManager()
    pm.start("python -m http.server 8888", "logs/test.log")
    
    time.sleep(1)
    
    result = pm.restart(timeout=5)
    
    assert result['status'] == 'running'
    assert result['log_file'] != "logs/test.log"  # Новый лог-файл
    
    pm.kill("SIGKILL")
```

### test_api.py

```python
def test_full_workflow():
    # Start
    response = client.post("/start", json={"command": "sleep 5"})
    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'running'
    pid = data['process_pid']
    
    # Status
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json()['process_pid'] == pid
    
    # Kill
    response = client.post("/kill?type=SIGTERM")
    assert response.status_code == 200
    assert response.json()['status'] == 'killed'
    
    # Status after kill
    response = client.get("/status")
    assert response.json()['status'] == 'killed'
```

## Деплой и запуск

### Разработка

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск в dev режиме
python -m src.main --port 8000

# Или через uvicorn напрямую с hot-reload
uvicorn src.main:app --reload --port 8000
```

### Production

```bash
# Через systemd service
# /etc/systemd/system/llm-shell.service

[Unit]
Description=LLM Shell API
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/llm_shell
Environment="LLM_SHELL_PORT=8000"
ExecStart=/path/to/venv/bin/python -m src.main
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker (опционально)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY logs/ ./logs/

ENV LLM_SHELL_PORT=8000
ENV LLM_SHELL_HOST=0.0.0.0

CMD ["python", "-m", "src.main"]
```
