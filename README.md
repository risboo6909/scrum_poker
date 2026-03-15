# Scrum Poker

A simple Scrum Poker app with a JavaScript frontend, a Python backend, and real-time updates over WebSocket.

Take a look at it live: https://risboo6909.org/poker/

## Features

- room creation by a leader with a shareable URL
- participant join flow by room link
- leader-controlled voting start
- hidden votes until `Reveal cards`
- participant votes plus average, median, and mode after reveal
- `Restart` for a new round
- real-time room synchronization over WebSocket
- rooms expire by TTL and are cleaned up lazily on requests
- no more than 10000 active rooms at the same time

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

By default, the app is available at `http://localhost:8000/poker/`.

## Docker

```bash
docker build -t scrum-poker .
docker run --rm -p 8000:8000 scrum-poker
```

If the app should live under a path prefix instead of the domain root, pass `BASE_PATH`:

```bash
docker run --rm -e PORT=8000 -e BASE_PATH=/poker -p 8000:8000 scrum-poker
```

Additional environment variables:

- `ROOM_TTL_SECONDS` — room TTL in seconds, default `86400`
- `MAX_ACTIVE_ROOMS` — maximum active room count, default `10000`

## Docker Compose

```bash
docker compose up --build
```

## Nginx Path Proxy

To proxy the app through Nginx under `/poker`:

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

If you need a different port inside the container:

```bash
docker run --rm -e PORT=8080 -p 8080:8080 scrum-poker
```
