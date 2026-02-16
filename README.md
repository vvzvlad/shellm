# LLM Shell

HTTP API для управления одиночным процессом в неблокирующем режиме. Подходит для LLM-агентов, чтобы запускать серверы/тесты, смотреть логи и перезапускать процессы без блокировки консоли.

## Быстрый старт

```bash
pip install -r requirements.txt
python -m src.main --port 8000
```

Проверка:

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

### GET /status

```bash
curl http://localhost:8000/status
```

### POST /kill

```bash
curl -X POST 'http://localhost:8000/kill?type=SIGTERM'
```

### POST /restart

```bash
curl -X POST 'http://localhost:8000/restart?timeout=5'
```

### GET /logs

```bash
curl 'http://localhost:8000/logs?lines=100'
curl 'http://localhost:8000/logs?seconds=30'
```

## Конфигурация

Можно через ENV:

```bash
export LLM_SHELL_PORT=8000
export LLM_SHELL_HOST=0.0.0.0
```

Или CLI:

```bash
python -m src.main --host 127.0.0.1 --port 8000
```

## Тесты

```bash
pytest -v
```

## Особенности

- Только один процесс одновременно
- Логи пишутся в `logs/` в JSON формате
- `shell=True` для поддержки `cd`, переменных и пайпов
- `lines` и `seconds` нельзя использовать вместе
