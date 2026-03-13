# Scrum Poker

Простой Scrum Poker на JavaScript-фронтенде и Python-бэкенде с обновлениями через WebSocket.

## Что есть

- создание комнаты лидером с выдачей URL
- подключение участников по ссылке
- запуск голосования лидером
- скрытые голоса до `Reveal cards`
- показ голосов, среднего, медианы и моды
- `Restart` для нового раунда
- синхронизация комнаты в реальном времени через WebSocket

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

По умолчанию приложение доступно на `http://localhost:8000`.

## Docker

```bash
docker build -t scrum-poker .
docker run --rm -p 8000:8000 scrum-poker
```

## Docker Compose

```bash
docker compose up --build
```

Если нужен другой порт внутри контейнера:

```bash
docker run --rm -e PORT=8080 -p 8080:8080 scrum-poker
```
