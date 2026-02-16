# LLM Shell - Руководство для LLM агентов

## Быстрый старт

LLM Shell - это HTTP API для управления процессами в неблокирующем режиме. Вы можете запускать серверы, тесты и другие команды, не блокируя себе консоль.

## Базовый URL

```
http://localhost:8000
```

## Типичные сценарии использования

### Сценарий 1: Разработка и тестирование веб-сервера

```bash
# 1. Запустить сервер
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "python -m http.server 8080"}'

# Ответ:
# {
#   "command": "python -m http.server 8080",
#   "status": "running",
#   "created_at": "2026-02-16T03:00:00Z",
#   "process_pid": 12345,
#   "log_file": "logs/2026-02-16_03-00-00.log"
# }

# 2. Проверить что сервер работает
curl http://localhost:8000/status

# 3. Запустить тесты (в своей консоли, не через LLM Shell)
pytest tests/test_api.py

# 4. Если тест упал - посмотреть логи сервера
curl 'http://localhost:8000/logs?lines=100'

# 5. Исправить код, перезапустить сервер
curl -X POST 'http://localhost:8000/restart?timeout=5'

# 6. Снова запустить тесты
pytest tests/test_api.py

# 7. Остановить сервер
curl -X POST 'http://localhost:8000/kill?type=SIGTERM'
```

### Сценарий 2: Дебаг долгоживущего процесса

```bash
# 1. Запустить процесс
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "node server.js"}'

# 2. Подождать 10 секунд
sleep 10

# 3. Посмотреть последние 50 строк логов
curl 'http://localhost:8000/logs?lines=50'

# 4. Посмотреть логи за последние 30 секунд
curl 'http://localhost:8000/logs?seconds=30'

# 5. Если нужно - убить процесс
curl -X POST 'http://localhost:8000/kill?type=SIGKILL'
```

### Сценарий 3: Работа с переменными окружения

```bash
# Запуск с переменной окружения
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "PORT=3000 DEBUG=true node server.js"}'
```

### Сценарий 4: Смена рабочей директории

```bash
# Переход в директорию перед запуском
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "cd myapp && npm start"}'
```

## Все доступные endpoints

### 1. POST /start - Запустить процесс

**Request:**
```json
{
  "command": "python -m http.server 8080"
}
```

**Response (201):**
```json
{
  "command": "python -m http.server 8080",
  "status": "running",
  "created_at": "2026-02-16T03:00:00Z",
  "process_pid": 12345,
  "log_file": "logs/2026-02-16_03-00-00.log"
}
```

**Ошибки:**
- 400: пустая команда
- 409: процесс уже запущен

### 2. GET /status - Статус процесса

**Response (200):**
```json
{
  "command": "python -m http.server 8080",
  "status": "running",  // "running" | "exited" | "killed"
  "created_at": "2026-02-16T03:00:00Z",
  "process_pid": 12345,
  "log_file": "logs/2026-02-16_03-00-00.log",
  "stopped_at": null,
  "exit_code": null
}
```

**Ошибки:**
- 404: процесс не запущен

### 3. POST /kill - Убить процесс

**Request:**
```bash
curl -X POST 'http://localhost:8000/kill?type=SIGTERM'
# или
curl -X POST 'http://localhost:8000/kill?type=SIGKILL'
```

**Response (200):**
```json
{
  "stopped_at": "2026-02-16T05:00:00Z",
  "exit_code": -15,
  "type": "SIGTERM",
  "status": "killed"
}
```

**Ошибки:**
- 404: процесс не запущен
- 400: процесс уже завершен

### 4. POST /restart - Перезапустить процесс

**Request:**
```bash
curl -X POST 'http://localhost:8000/restart?timeout=10'
```

`timeout` - сколько секунд ждать graceful shutdown (SIGTERM) перед force kill (SIGKILL). По умолчанию 10.

**Response (200):** - аналогично /start

**Ошибки:**
- 404: процесс не запущен

### 5. GET /logs - Получить логи

**Варианты запроса:**

```bash
# Все логи
curl 'http://localhost:8000/logs'

# Последние 100 строк
curl 'http://localhost:8000/logs?lines=100'

# Логи за последние 30 секунд
curl 'http://localhost:8000/logs?seconds=30'
```

**ВАЖНО:** нельзя указывать `lines` и `seconds` одновременно!

**Response (200):**
```json
{
  "log_file": "logs/2026-02-16_03-00-00.log",
  "total_lines": 1523,
  "lines_returned": 100,
  "content": "Serving HTTP on 0.0.0.0 port 8080...\n127.0.0.1 - - [16/Feb/2026 03:01:23] \"GET / HTTP/1.1\" 200 -\n..."
}
```

**Ошибки:**
- 400: указаны и lines и seconds
- 404: процесс не запущен или лог-файл не найден

### 6. GET /health - Health check

**Response (200):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": 86400
}
```

## Ограничения и важные моменты

1. **Только один процесс**: нельзя запустить второй процесс пока первый работает
2. **Нужно явно убивать**: процессы не останавливаются автоматически
3. **Логи растут**: ротации нет, файлы могут быть большими
4. **При restart**: создается новый лог-файл, старые логи сохраняются

## Типичные ошибки

### Попытка запустить второй процесс

```bash
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "sleep 100"}'
  
# Попытка запустить еще один
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"command": "echo test"}'

# Ошибка 409: {"error": "Process already running"}
```

**Решение:** сначала убить старый процесс через `/kill`

### Убить уже завершенный процесс

```bash
curl -X POST 'http://localhost:8000/kill?type=SIGTERM'
# Ошибка 400: {"error": "Process already exited"}
```

**Решение:** проверить статус через `/status`

### Одновременно lines и seconds

```bash
curl 'http://localhost:8000/logs?lines=100&seconds=30'
# Ошибка 400: {"error": "Cannot specify both 'lines' and 'seconds'"}
```

**Решение:** использовать только один параметр

## Рабочий процесс для LLM агента

### Workflow 1: Итеративная разработка сервера

```
1. Написать код сервера
2. POST /start - запустить сервер
3. Запустить тесты (в своей консоли)
4. GET /logs - посмотреть логи сервера
5. Если тесты упали:
   - Проанализировать логи
   - Исправить код
   - POST /restart - перезапустить сервер
   - Вернуться к шагу 3
6. POST /kill - остановить сервер
```

### Workflow 2: Дебаг периодических ошибок

```
1. POST /start - запустить приложение
2. Подождать (sleep)
3. GET /logs?seconds=60 - посмотреть логи за последнюю минуту
4. Проанализировать проблему
5. POST /restart - перезапустить с исправлениями
6. Повторить
```

### Workflow 3: Мониторинг долгоживущих процессов

```
1. POST /start - запустить процесс
2. Периодически:
   - GET /status - проверить жив ли
   - GET /logs?lines=50 - посмотреть последние логи
3. Если процесс упал:
   - GET /logs - получить все логи
   - Проанализировать
   - POST /start - запустить заново
```

## Примеры команд для разных стеков

### Python

```bash
# Web server
{"command": "python -m http.server 8080"}
{"command": "uvicorn main:app --port 8000"}
{"command": "flask run --port 5000"}

# С переменными
{"command": "PORT=8000 DEBUG=1 python server.py"}

# В другой директории
{"command": "cd backend && python manage.py runserver"}
```

### Node.js

```bash
# Express server
{"command": "node server.js"}
{"command": "npm start"}

# С переменными
{"command": "PORT=3000 NODE_ENV=development node server.js"}

# В другой директории
{"command": "cd frontend && npm run dev"}
```

### Go

```bash
{"command": "go run main.go"}
{"command": "cd cmd/server && go run ."}
```

### Rust

```bash
{"command": "cargo run"}
{"command": "cd backend && cargo run --release"}
```

## Python клиент (пример)

```python
import requests
import time

class LLMShellClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    def start(self, command):
        response = requests.post(
            f"{self.base_url}/start",
            json={"command": command}
        )
        response.raise_for_status()
        return response.json()
    
    def status(self):
        response = requests.get(f"{self.base_url}/status")
        response.raise_for_status()
        return response.json()
    
    def kill(self, signal_type="SIGTERM"):
        response = requests.post(
            f"{self.base_url}/kill",
            params={"type": signal_type}
        )
        response.raise_for_status()
        return response.json()
    
    def restart(self, timeout=10):
        response = requests.post(
            f"{self.base_url}/restart",
            params={"timeout": timeout}
        )
        response.raise_for_status()
        return response.json()
    
    def logs(self, lines=None, seconds=None):
        params = {}
        if lines:
            params["lines"] = lines
        if seconds:
            params["seconds"] = seconds
        
        response = requests.get(
            f"{self.base_url}/logs",
            params=params
        )
        response.raise_for_status()
        return response.json()

# Использование
client = LLMShellClient()

# Запустить сервер
result = client.start("python -m http.server 8080")
print(f"Started process {result['process_pid']}")

# Подождать
time.sleep(5)

# Посмотреть логи
logs = client.logs(lines=10)
print(logs['content'])

# Остановить
client.kill()
```

## Проверка что API работает

```bash
# Health check
curl http://localhost:8000/health

# Должен вернуть:
# {"status":"healthy","version":"1.0.0","uptime":123}
```
