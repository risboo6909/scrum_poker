# Scrum Poker

A simple Scrum Poker app with a JavaScript frontend, a Python backend, and real-time updates over WebSocket.

Take a look at it live: https://risboo6909.org/poker/

## Features

- room creation by a leader with a shareable URL
- participant join flow by room link
- leader-controlled voting start
- starting a round requires at least two connected participants, including the leader
- optional automatic reveal when every current participant has voted
- hidden votes until `Reveal cards`
- participant votes plus median and most common vote after reveal
- `Start vote` for each new numbered round
- Fibonacci estimates with a simple name-only room creation form
- private room-session cookies protect votes and leader actions
- real-time room synchronization over WebSocket
- rooms expire by TTL and are cleaned up lazily on requests
- no more than 10000 active rooms at the same time

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.app
```

By default, the app is available at `http://localhost:8000/`. Compose configures `http://localhost:8000/poker/`.

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

- `COUNTER_DB_PATH` — persistent aggregate counter file; defaults to `data/counter.sqlite3` locally. Compose stores it in the `counter-data` named volume at `/data/counter.sqlite3`.
- `COUNTER_INITIAL_VALUE` — optional initial total for migration, used only when creating the counter. Existing totals are never overwritten.

Only the total rooms-created counter is saved. Rooms, participants, and votes still disappear on restart. Keep the Compose volume to retain the total; `docker compose down -v` deletes it. For standalone Docker, mount a volume with `-v scrum-poker-counter:/data -e COUNTER_DB_PATH=/data/counter.sqlite3`.

- `ROOM_TTL_SECONDS` — room TTL in seconds, default `86400`
- `MAX_ACTIVE_ROOMS` — maximum active room count, default `10000`

## Docker Compose

```bash
docker compose up --build
```

## Verification

Python application code lives in `src/`; regression tests live in `tests/`. Run `python -m unittest discover -s tests -t . -v` from the project root after installing the requirements. Tests cover private sessions, votes, round transitions, room expiry/capacity, auto-reveal, statistics, concurrency, and counter persistence.

`GET /health` (or `/poker/health` with the Compose prefix) checks both SQLite stores. The Docker image includes a healthcheck. Run one application process: room storage is intentionally in memory. Session cookies are HttpOnly and SameSite=Strict, and Secure when served through HTTPS. Nginx must overwrite `X-Forwarded-Proto` and preserve `Host`, as in the example below.

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
