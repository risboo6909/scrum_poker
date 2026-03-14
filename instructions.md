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
5. After reveal, show each participant's estimate, plus aggregate statistics.
6. After a round ends, the team should be able to start voting again.

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
- path-prefix deployment via `BASE_PATH` with `/poker` as the default deployed path in compose

Current behavior:

- A leader creates a room and gets a shareable URL.
- Other users join by opening that room URL and submitting their name.
- The leader can start voting and reveal cards.
- Starting a new vote round is done with `Start vote`; there is no separate `Restart` button in the UI.
- Votes are hidden until reveal.
- After reveal, the UI shows participant votes plus `median` and `most common vote`.
- Room updates are pushed in real time over WebSocket.
- Rooms expire automatically after inactivity.
- Active room count is capped at 10000 by default.
- The landing screen shows a small counter for rooms created since process startup.
- The UI supports light and dark themes and stores the preference in browser local storage.
- Room reveal includes a card reveal animation for participant cards.
- If a round has a most common vote, reveal also triggers a short party-popper confetti animation.

## Source Of Truth

When making changes, keep these files aligned:

- [instructions.md](/Users/risboo6909/ScrumPoker/instructions.md): English agent-facing product and engineering spec
- [app.py](/Users/risboo6909/ScrumPoker/app.py): backend API, room lifecycle, WebSocket broadcast
- [templates/index.html](/Users/risboo6909/ScrumPoker/templates/index.html): server-rendered shell and labels
- [static/app.js](/Users/risboo6909/ScrumPoker/static/app.js): frontend state and user actions
- [static/styles.css](/Users/risboo6909/ScrumPoker/static/styles.css): visual theme, animation, and layout
- [Dockerfile](/Users/risboo6909/ScrumPoker/Dockerfile) and [docker-compose.yml](/Users/risboo6909/ScrumPoker/docker-compose.yml): runtime packaging

## Design Constraints

- Keep the product simple. Do not introduce unnecessary framework complexity.
- Prefer small, readable changes over abstract architecture.
- Preserve the room flow: create, join, start, vote, reveal, start again.
- Keep leader-only actions restricted to the leader.
- Do not reveal participant votes before the reveal step.
- Keep the app functional behind a reverse proxy such as Nginx.
- Keep room retention simple: TTL-based cleanup is preferred over complex schedulers.
- Keep the frontend buildless unless there is a strong reason to introduce a toolchain.
- Prefer small UI polish and direct DOM logic over adding frontend framework complexity.

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
- Do not reintroduce `average` into the reveal stats unless the product requirements explicitly change.
- Do not reintroduce a dedicated `Restart` button unless the product requirements explicitly change.
- Keep the app working under the `/poker` path prefix unless deployment requirements explicitly change.

## Suggested Next Enhancements

- Add healthchecks for container/runtime verification.
- Add Nginx example config for reverse proxying HTTP and WebSocket traffic.
- Add basic automated tests for room lifecycle and stats calculation.
- Add configurable planning decks if needed.
