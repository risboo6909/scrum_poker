# Scrum Poker Agent Instructions

## Project Goal

Build and evolve a simple Scrum Poker application.

The project should stay lightweight, easy to run, and easy to modify.

## Original Request

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
- Public participant IDs are not credentials. Create/join sets a private HttpOnly, SameSite=Strict room cookie (Secure over HTTPS); HTTP actions, private state, and WebSocket connections require the matching session. Only credential hashes are stored in memory.
- Requests serialize shared room/database state with a reentrant lock; socket receive loops never hold it. Deploy one application process.
- Other users join by opening that room URL and submitting their name.
- Opening a room URL for a room that does not exist immediately shows `Room not found` and disables the join form.
- The leader can start voting and reveal cards.
- Starting voting requires at least two connected participants, including the leader. The UI disables Start vote while waiting, and the backend enforces the same rule. A round already in progress continues if someone disconnects.
- The leader can optionally enable automatic reveal. When enabled, the server reveals as soon as every participant currently in the room has submitted a numeric estimate or `Need context`.
- Starting a new vote round is done with `Start vote`; there is no separate `Restart` button in the UI.
- The first round is 1; starting after reveal increments it. Starting during voting and revealing outside voting return 409. Legacy `/restart` is retained only from revealed to lobby and increments once.
- Votes must be finite JSON numbers exactly present in the room deck, or `abstain`; strings and booleans are rejected.
- Automatic reveal is checked after votes, enabling the option, kicks, and disconnect cleanup. Abstentions count as submissions.
- The leader can remove non-leader participants from the participant list.
- The leader can end the whole room session from the top-left close control and return to the landing screen.
- Votes are hidden until reveal.
- Before reveal, each participant can see their own selected card on their own participant card, while other participants still only see a hidden state.
- The current user is labeled inline in the participant list as `Name (You)`.
- After reveal, the UI shows participant votes plus `median` and `most common vote`.
- Room updates are pushed in real time over WebSocket.
- Rooms expire automatically after inactivity.
- Active room count is capped at 10000 by default.
- The landing screen shows total rooms created, persisted separately in a file-backed SQLite counter. Only this aggregate survives restarts; rooms and votes remain in memory. Compose mounts a named volume for the counter.
- The UI supports light and dark themes and stores the preference in browser local storage.
- Cards use portrait playing-card proportions, a single centered estimate, and patterned burgundy backs. Higher estimates make only the estimate numeral grow and glow; dark mode uses subdued dark faces and backs.
- Room reveal turns participant cards over with a 3D flip; reduced-motion preferences disable the transition. Own selected estimates remain visible before reveal.
- The reveal transition must animate in current Chrome and Safari. Version static assets with a query parameter so a deployed UI change cannot combine stale JavaScript or CSS with a new counterpart.
- When a participant chooses an estimate, only the card on their own participant tile turns over to reveal that estimate; other participants continue to see a card back until the leader reveals the round.
- Reveal triggers confetti only when at least two participants all submitted the same numeric vote; abstentions and missing votes prevent celebration.
- `/health` under the configured prefix checks both databases; Docker includes a healthcheck.

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
- When a room URL is invalid or expired, fail early on page load instead of waiting for a join attempt.
- Do not reveal participant votes to other participants before the reveal step.
- Keep the app functional behind a reverse proxy such as Nginx.
- Keep room retention simple: TTL-based cleanup is preferred over complex schedulers.
- Keep the frontend buildless unless there is a strong reason to introduce a toolchain.
- Prefer small UI polish and direct DOM logic over adding frontend framework complexity.

## Non-Goals For Now

- No authentication system beyond participant identity within a room
- No durable persistence of rooms, participants, or votes; only the aggregate rooms-created counter is persistent.
- No advanced permissions model
- No admin dashboard
- No heavy frontend build toolchain unless clearly necessary

## Change Guidelines For Future Agents

- Maintain backward compatibility for the main room flow unless the spec is intentionally changed.
- If adding features, prefer extending the existing REST + WebSocket model rather than replacing it.
- If adding infrastructure, keep local startup simple.
- If introducing new behavior, update this file so the next agent has an accurate spec.
- Do not reintroduce `average` into the reveal stats unless the product requirements explicitly change.
- Do not reintroduce a dedicated `Restart` button unless the product requirements explicitly change.
- Keep the app working under the `/poker` path prefix unless deployment requirements explicitly change.

## Verification

- Run `python -m unittest discover -v` and `node --check static/app.js` before deployment.
- `instructions.md` is the authoritative product specification; no historical external spec is required.
- Nginx proxy configuration is documented in README.md. Preserve the named counter volume during deployments.
