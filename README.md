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

По умолчанию приложение доступно на `http://localhost:8000/poker/`.

## Docker

```bash
docker build -t scrum-poker .
docker run --rm -p 8000:8000 scrum-poker
```

Если приложение должно жить под путём, а не в корне, передай `BASE_PATH`:

```bash
docker run --rm -e PORT=8000 -e BASE_PATH=/poker -p 8000:8000 scrum-poker
```

## Docker Compose

```bash
docker compose up --build
```

## Nginx Path Proxy

Для проксирования через Nginx по пути `/poker`:

```nginx
location = /poker {
    return 301 /poker/;
}

location /poker/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

Если нужен другой порт внутри контейнера:

```bash
docker run --rm -e PORT=8080 -p 8080:8080 scrum-poker
```
