# Scrum Poker Agent Instructions

## Project Goal

Build and evolve a simple Scrum Poker application.

The project should stay lightweight, easy to run, and easy to modify.

## Original Request Translated To English

Create a Scrum Poker app in JavaScript.

Requirements:

1. It must be simple.
2. A person creates a room, enters their name, and receives a URL containing the room ID. This person becomes the room leader.
3. The leader shares that URL with other people. They join the room and enter their names.
4. When the leader clicks `Start vote`, each participant submits an estimate independently. Estimates must stay hidden from other participants until the leader clicks `Reveal cards`.
5. After reveal, show each participant's estimate, plus the median, average, and mode.
6. After clicking `Restart`, the process should start again from step 4.

Backend constraints:

- Use a very simple Python backend.
- Use in-memory SQLite for room and vote storage.

Deployment constraints:

- Package everything in Docker.
- The service must listen on a defined port.
- The backend must also serve the JavaScript frontend.
- The app is intended to sit behind Nginx later.

## Current Implementation

The project currently uses:

- Python `Flask` for the backend
- `Flask-Sock` for WebSocket room updates
- in-memory SQLite for persistence during process lifetime
- plain JavaScript, HTML, and CSS for the frontend
- Docker and `docker compose` for local/containerized runs

Current behavior:

- A leader creates a room and gets a shareable URL.
- Other users join by opening that room URL and submitting their name.
- The leader can start voting, reveal cards, and restart the round.
- Votes are hidden until reveal.
- After reveal, the UI shows participant votes and aggregate stats.
- Room updates are pushed in real time over WebSocket.

## Source Of Truth

When making changes, keep these files aligned:

- [instructions.md](/Users/risboo6909/ScrumPoker/instructions.md): English agent-facing product and engineering spec
- [app.py](/Users/risboo6909/ScrumPoker/app.py): backend API, room lifecycle, WebSocket broadcast
- [static/app.js](/Users/risboo6909/ScrumPoker/static/app.js): frontend state and user actions
- [Dockerfile](/Users/risboo6909/ScrumPoker/Dockerfile) and [docker-compose.yml](/Users/risboo6909/ScrumPoker/docker-compose.yml): runtime packaging

## Design Constraints

- Keep the product simple. Do not introduce unnecessary framework complexity.
- Prefer small, readable changes over abstract architecture.
- Preserve the room flow: create, join, start, vote, reveal, restart.
- Keep leader-only actions restricted to the leader.
- Do not reveal participant votes before the reveal step.
- Keep the app functional behind a reverse proxy such as Nginx.

## Non-Goals For Now

- No authentication system beyond participant identity within a room
- No durable database persistence across container restarts
- No advanced permissions model
- No admin dashboard
- No heavy frontend build toolchain unless clearly necessary

## Change Guidelines For Future Agents

- Maintain backward compatibility for the main room flow unless the spec is intentionally changed.
- If adding features, prefer extending the existing REST + WebSocket model rather than replacing it.
- If adding infrastructure, keep local startup simple.
- If introducing new behavior, update this file so the next agent has an accurate spec.
- If the implementation diverges from `tz.md`, document the reason here.

## Suggested Next Enhancements

- Add healthchecks for container/runtime verification.
- Add Nginx example config for reverse proxying HTTP and WebSocket traffic.
- Add basic automated tests for room lifecycle and stats calculation.
- Add configurable planning decks if needed.
