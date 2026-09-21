import json
import hashlib
import math
import secrets
import os
import sqlite3
import statistics
import threading
import time
import uuid
from pathlib import Path
from contextlib import closing
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, render_template, request, send_from_directory
from flask_sock import Sock
from counter import RoomCounter


BASE_PATH = os.environ.get("BASE_PATH", "").strip().strip("/")
BASE_PREFIX = f"/{BASE_PATH}" if BASE_PATH else ""
ROOM_TTL_SECONDS = int(os.environ.get("ROOM_TTL_SECONDS", "86400"))
MAX_ACTIVE_ROOMS = int(os.environ.get("MAX_ACTIVE_ROOMS", "10000"))
DECKS = {
    "fibonacci": {
        "id": "fibonacci",
        "label": "Fibonacci",
        "description": "Classic Scrum Poker story points.",
        "options": [1, 2, 3, 5, 8, 13, 21],
    },
    "pu": {
        "id": "pu",
        "label": "PU",
        "description": "Preliminary Units, where 0.5 PU = 4 working hours.",
        "options": [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8],
    },
}

app = Flask(__name__, static_folder="static", static_url_path=None)
sock = Sock(app)
connections = {}
connections_lock = threading.Lock()
state_lock = threading.RLock()


def cookie_name(room_id):
    return f"poker_session_{room_id}"


def authenticated_participant(room_id):
    token = request.cookies.get(cookie_name(room_id), "")
    return get_db().execute(
        "SELECT * FROM participants WHERE room_id = ? AND credential_hash = ?",
        (room_id, hashlib.sha256(token.encode()).hexdigest()),
    ).fetchone() if token else None


def set_participant_cookie(response, room_id, token):
    response.set_cookie(cookie_name(room_id), token, httponly=True,
                        secure=request.is_secure or request.headers.get("X-Forwarded-Proto") == "https",
                        samesite="Strict", path=f"{BASE_PREFIX}/", max_age=ROOM_TTL_SECONDS)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.before_request
def guard_request():
    # Socket handlers lock only connection lifecycle operations, never receive().
    if request.path.startswith(f"{BASE_PREFIX}/ws/"):
        return None
    if request.method not in ("GET", "POST"):
        return None
    state_lock.acquire()
    g.state_locked = True
    if request.method == "POST":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("Expected a JSON object")
    room_id = (request.view_args or {}).get("room_id")
    if not room_id or not request.path.startswith(f"{BASE_PREFIX}/api/"):
        return None
    if not room_exists(room_id):
        return error("Room not found", 404)
    if request.endpoint == "join_room":
        return None
    supplied_id = request.args.get("participantId") if request.method == "GET" else payload.get("participantId")
    participant = authenticated_participant(room_id)
    if request.method == "GET" and not supplied_id:
        return None
    if not participant or participant["id"] != supplied_id:
        return error("Invalid participant session", 403)


@app.teardown_request
def unlock_request(exception):
    if getattr(g, "state_locked", False):
        g.state_locked = False
        if hasattr(app, "_db"):
            app._db.rollback()
        state_lock.release()


@app.after_request
def private_api_response(response):
    if request.path.startswith(f"{BASE_PREFIX}/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
room_counter = RoomCounter(
    os.environ.get("COUNTER_DB_PATH", str(Path(__file__).parent / "data" / "counter.sqlite3")),
    initial_value=int(os.environ.get("COUNTER_INITIAL_VALUE", "0")),
)
ASSET_VERSION = str(max(
    (Path(__file__).parent / "static" / "app.js").stat().st_mtime_ns,
    (Path(__file__).parent / "static" / "styles.css").stat().st_mtime_ns,
))


def get_db():
    if not hasattr(app, "_db"):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            CREATE TABLE rooms (
                id TEXT PRIMARY KEY,
                phase TEXT NOT NULL DEFAULT 'lobby',
                round_number INTEGER NOT NULL DEFAULT 1,
                deck TEXT NOT NULL DEFAULT 'fibonacci',
                auto_reveal INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_activity_at INTEGER NOT NULL
            );

            CREATE TABLE participants (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                name TEXT NOT NULL,
                credential_hash TEXT NOT NULL,
                is_leader INTEGER NOT NULL DEFAULT 0,
                joined_order INTEGER NOT NULL,
                FOREIGN KEY(room_id) REFERENCES rooms(id)
            );

            CREATE TABLE votes (
                participant_id TEXT NOT NULL,
                room_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                value REAL,
                abstained INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (participant_id, room_id, round_number),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(room_id) REFERENCES rooms(id)
            );
            """
        )
        app._db = db
    return app._db


def add_connection(room_id, participant_id, ws):
    with connections_lock:
        room_connections = connections.setdefault(room_id, [])
        room_connections.append({"participant_id": participant_id, "ws": ws})


def remove_connection(room_id, ws):
    with connections_lock:
        room_connections = connections.get(room_id, [])
        remaining = [entry for entry in room_connections if entry["ws"] is not ws]
        if remaining:
            connections[room_id] = remaining
        else:
            connections.pop(room_id, None)


def disconnect_participant(room_id, participant_id):
    with connections_lock:
        room_connections = list(connections.get(room_id, []))

    for entry in room_connections:
        if entry["participant_id"] != participant_id:
            continue
        try:
            entry["ws"].close()
        except Exception:
            pass
        remove_connection(room_id, entry["ws"])


def disconnect_room(room_id):
    with connections_lock:
        room_connections = list(connections.get(room_id, []))

    for entry in room_connections:
        try:
            entry["ws"].close()
        except Exception:
            pass
        remove_connection(room_id, entry["ws"])


def online_participant_ids(room_id):
    with connections_lock:
        room_connections = connections.get(room_id, [])
        return {entry["participant_id"] for entry in room_connections}


def now_ts():
    return int(time.time())


def expiry_cutoff():
    return now_ts() - ROOM_TTL_SECONDS


def cleanup_expired_rooms():
    db = get_db()
    expired_ids = [
        row["id"]
        for row in db.execute(
            "SELECT id FROM rooms WHERE last_activity_at < ?",
            (expiry_cutoff(),),
        ).fetchall()
    ]

    if not expired_ids:
        return

    placeholders = ",".join("?" for _ in expired_ids)
    db.execute(f"DELETE FROM votes WHERE room_id IN ({placeholders})", expired_ids)
    db.execute(f"DELETE FROM participants WHERE room_id IN ({placeholders})", expired_ids)
    db.execute(f"DELETE FROM rooms WHERE id IN ({placeholders})", expired_ids)
    db.commit()

    for room_id in expired_ids:
        disconnect_room(room_id)


def active_room_count():
    cleanup_expired_rooms()
    db = get_db()
    return db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]


def touch_room(room_id):
    db = get_db()
    db.execute(
        "UPDATE rooms SET last_activity_at = ? WHERE id = ?",
        (now_ts(), room_id),
    )
    db.commit()


def room_exists(room_id):
    cleanup_expired_rooms()
    db = get_db()
    row = db.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    return row is not None


def participant_in_room(room_id, participant_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM participants WHERE room_id = ? AND id = ?",
        (room_id, participant_id),
    ).fetchone()


def remove_participant(room_id, participant_id):
    disconnect_participant(room_id, participant_id)
    db = get_db()
    db.execute(
        "DELETE FROM votes WHERE room_id = ? AND participant_id = ?",
        (room_id, participant_id),
    )
    db.execute(
        "DELETE FROM participants WHERE room_id = ? AND id = ?",
        (room_id, participant_id),
    )
    db.commit()


def remove_room(room_id):
    disconnect_room(room_id)
    db = get_db()
    db.execute("DELETE FROM votes WHERE room_id = ?", (room_id,))
    db.execute("DELETE FROM participants WHERE room_id = ?", (room_id,))
    db.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
    db.commit()


def prune_inactive_participants(room_id, keep_voted):
    db = get_db()
    room = db.execute(
        "SELECT round_number FROM rooms WHERE id = ?",
        (room_id,),
    ).fetchone()
    if not room:
        return

    online_ids = online_participant_ids(room_id)
    participants = db.execute(
        """
        SELECT
            p.id,
            p.is_leader,
            EXISTS(
                SELECT 1
                FROM votes v
                WHERE v.room_id = p.room_id
                    AND v.participant_id = p.id
                    AND v.round_number = ?
            ) AS has_vote
        FROM participants p
        WHERE p.room_id = ?
        """,
        (room["round_number"], room_id),
    ).fetchall()

    removable_ids = []
    for participant in participants:
        if participant["id"] in online_ids:
            continue
        if participant["is_leader"]:
            continue
        if keep_voted and participant["has_vote"]:
            continue
        removable_ids.append(participant["id"])

    for participant_id in removable_ids:
        remove_participant(room_id, participant_id)


def require_leader(room_id, participant_id):
    participant = participant_in_room(room_id, participant_id)
    if not participant or not participant["is_leader"]:
        return None, (jsonify({"error": "Only the room leader can do that"}), 403)
    return participant, None


def parse_vote_value(raw_value):
    if raw_value == "abstain":
        return "abstain"
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def serialize_value(value):
    if float(value).is_integer():
        return int(value)
    return float(value)


def room_deck(deck_id):
    return DECKS.get(deck_id, DECKS["fibonacci"])


def compute_stats(values):
    if not values:
        return None

    median = statistics.median(values)
    unanimous = len(values) >= 2 and len(set(values)) == 1
    modes = statistics.multimode(values)
    mode = None
    if modes:
        occurrences = values.count(modes[0])
        if occurrences > 1:
            mode = min(modes)

    return {
        "median": serialize_value(median),
        "mode": serialize_value(mode) if mode is not None else None,
        "unanimous": unanimous,
    }


def reveal_if_everyone_voted(db, room_id, round_number):
    room = db.execute("SELECT phase, auto_reveal FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room or room["phase"] != "voting" or not room["auto_reveal"]:
        return False
    counts = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM participants WHERE room_id = ?) AS participants,
            (SELECT COUNT(*) FROM votes WHERE room_id = ? AND round_number = ?) AS votes
        """,
        (room_id, room_id, round_number),
    ).fetchone()
    if counts["participants"] > 0 and counts["participants"] == counts["votes"]:
        db.execute("UPDATE rooms SET phase = 'revealed' WHERE id = ?", (room_id,))
        return True
    return False


def check_auto_reveal(room_id):
    db = get_db()
    room = db.execute("SELECT round_number FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room:
        reveal_if_everyone_voted(db, room_id, room["round_number"])
        db.commit()


def serialize_room(room_id):
    cleanup_expired_rooms()
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        return None
    online_ids = online_participant_ids(room_id)
    deck = room_deck(room["deck"])

    participants = db.execute(
        """
        SELECT
            p.id,
            p.name,
            p.is_leader,
            v.value,
            COALESCE(v.abstained, 0) AS abstained
        FROM participants p
        LEFT JOIN votes v
            ON v.participant_id = p.id
            AND v.room_id = p.room_id
            AND v.round_number = ?
        WHERE p.room_id = ?
        ORDER BY p.joined_order ASC
        """,
        (room["round_number"], room_id),
    ).fetchall()

    revealed_values = []
    serialized_participants = []
    for participant in participants:
        abstained = bool(participant["abstained"])
        has_vote = participant["value"] is not None or abstained
        vote_value = "abstain" if abstained else (
            serialize_value(participant["value"]) if participant["value"] is not None else None
        )
        if room["phase"] == "revealed" and participant["value"] is not None:
            revealed_values.append(vote_value)

        serialized_participants.append(
            {
                "id": participant["id"],
                "name": participant["name"],
                "isLeader": bool(participant["is_leader"]),
                "isOnline": participant["id"] in online_ids,
                "hasVoted": has_vote,
                "hasAbstained": abstained,
                "vote": vote_value if room["phase"] == "revealed" else None,
            }
        )

    stats = compute_stats(revealed_values) if room["phase"] == "revealed" else None
    if stats:
        stats["unanimous"] = stats["unanimous"] and len(revealed_values) == len(participants)
    return {
        "id": room["id"],
        "phase": room["phase"],
        "roundNumber": room["round_number"],
        "autoReveal": bool(room["auto_reveal"]),
        "deck": deck,
        "participants": serialized_participants,
        "stats": stats,
    }


def get_viewer(room_id, participant_id):
    participant = participant_in_room(room_id, participant_id) if participant_id else None
    viewer_vote = None
    if participant:
        viewer_vote_row = get_db().execute(
            """
            SELECT v.value, COALESCE(v.abstained, 0) AS abstained
            FROM votes v
            JOIN rooms r ON r.id = v.room_id
            WHERE v.room_id = ? AND v.participant_id = ? AND v.round_number = r.round_number
            """,
            (room_id, participant_id),
        ).fetchone()
        if viewer_vote_row:
            viewer_vote = "abstain" if viewer_vote_row["abstained"] else serialize_value(viewer_vote_row["value"])

    return {
        "participantId": participant["id"] if participant else None,
        "isLeader": bool(participant["is_leader"]) if participant else False,
        "name": participant["name"] if participant else None,
        "currentVote": viewer_vote,
    }


def room_payload(room_id, participant_id):
    return {
        "room": serialize_room(room_id),
        "viewer": get_viewer(room_id, participant_id),
    }


def broadcast_room(room_id):
    with connections_lock:
        room_connections = list(connections.get(room_id, []))

    for entry in room_connections:
        try:
            entry["ws"].send(json.dumps(room_payload(room_id, entry["participant_id"])))
        except Exception:
            remove_connection(room_id, entry["ws"])


def error(message, code=400):
    return jsonify({"error": message}), code


def render_index():
    return render_template(
        "index.html",
        base_prefix=BASE_PREFIX,
        total_rooms_created=room_counter.read(),
        asset_version=ASSET_VERSION,
    )


@app.get(f"{BASE_PREFIX}/")
def index():
    return render_index()


@app.get(f"{BASE_PREFIX}/health")
def health():
    get_db().execute("SELECT 1").fetchone()
    room_counter.read()
    return jsonify({"status": "ok"})


if BASE_PREFIX:
    @app.get(f"{BASE_PREFIX}")
    def index_without_slash():
        return render_index()


@app.get(f"{BASE_PREFIX}/room/<room_id>")
def room_page(room_id):
    return render_index()


@app.get(f"{BASE_PREFIX}/room/<room_id>/")
def room_page_with_slash(room_id):
    return render_index()


@app.get(f"{BASE_PREFIX}/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


@sock.route(f"{BASE_PREFIX}/ws/rooms/<room_id>")
def room_socket(ws, room_id):
    handle_room_socket(ws, room_id)


def handle_room_socket(ws, room_id):
    with state_lock:
        origin = request.headers.get("Origin")
        if origin and (urlsplit(origin).netloc != request.host or urlsplit(origin).scheme not in ("http", "https")):
            ws.close()
            return
        participant_id = request.args.get("participantId")
        participant = authenticated_participant(room_id) if room_exists(room_id) else None
        if not participant or participant["id"] != participant_id:
            ws.close()
            return
        touch_room(room_id)
        add_connection(room_id, participant_id, ws)
        broadcast_room(room_id)

    try:
        while True:
            message = ws.receive()
            if message is None:
                break
    finally:
        with state_lock:
            remove_connection(room_id, ws)
            prune_inactive_participants(room_id, keep_voted=True)
            check_auto_reveal(room_id)
            broadcast_room(room_id)


@app.post(f"{BASE_PREFIX}/api/rooms")
def create_room():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    name = name.strip() if isinstance(name, str) else ""
    deck_id = payload.get("deck", "fibonacci")
    if not isinstance(deck_id, str) or deck_id not in DECKS:
        return error("Unknown deck")
    if not name or len(name) > 40:
        return error("Name must contain 1 to 40 characters")

    if active_room_count() >= MAX_ACTIVE_ROOMS:
        return error("Room limit reached, please try again later", 503)

    room_id = uuid.uuid4().hex[:8]
    participant_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    db = get_db()
    while db.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone():
        room_id = uuid.uuid4().hex[:8]
    created_at = now_ts()

    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            INSERT INTO rooms (id, deck, created_at, last_activity_at)
            VALUES (?, ?, ?, ?)
            """,
            (room_id, deck_id, created_at, created_at),
        )
        cursor.execute(
            """
            INSERT INTO participants (id, room_id, name, credential_hash, is_leader, joined_order)
            VALUES (?, ?, ?, ?, 1, 1)
            """,
            (participant_id, room_id, name, hashlib.sha256(token.encode()).hexdigest()),
        )
        db.commit()
        room_counter.increment()

    response = jsonify(
        {
            "roomId": room_id,
            "participantId": participant_id,
            "room": serialize_room(room_id),
        }
    )
    broadcast_room(room_id)
    return set_participant_cookie(response, room_id, token)


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/join")
def join_room(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 40:
        return error("Name must contain 1 to 40 characters")

    db = get_db()
    participant_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    joined_order = (
        db.execute(
            "SELECT COALESCE(MAX(joined_order), 0) + 1 FROM participants WHERE room_id = ?",
            (room_id,),
        ).fetchone()[0]
    )

    db.execute(
        """
        INSERT INTO participants (id, room_id, name, credential_hash, is_leader, joined_order)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (participant_id, room_id, name, hashlib.sha256(token.encode()).hexdigest(), joined_order),
    )
    db.commit()
    touch_room(room_id)

    response = jsonify(
        {
            "roomId": room_id,
            "participantId": participant_id,
            "room": serialize_room(room_id),
        }
    )
    broadcast_room(room_id)
    return set_participant_cookie(response, room_id, token)


@app.get(f"{BASE_PREFIX}/api/rooms/<room_id>")
def get_room(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    participant_id = request.args.get("participantId")
    if participant_id and not participant_in_room(room_id, participant_id):
        return error("Participant not found in room", 404)

    touch_room(room_id)
    return jsonify(room_payload(room_id, participant_id))


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/start")
def start_vote(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    participant_id = payload.get("participantId")
    _, leader_error = require_leader(room_id, participant_id)
    if leader_error:
        return leader_error

    db = get_db()
    room = db.execute("SELECT phase, round_number FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room["phase"] == "voting":
        return error("Voting is already in progress", 409)
    online_ids = online_participant_ids(room_id)
    participant_ids = {row["id"] for row in db.execute(
        "SELECT id FROM participants WHERE room_id = ?", (room_id,)
    ).fetchall()}
    connected_ids = online_ids & participant_ids
    if participant_id not in connected_ids or len(connected_ids) < 2:
        return error("At least two connected participants are required to start voting", 409)
    prune_inactive_participants(room_id, keep_voted=False)
    db.execute(
        "DELETE FROM votes WHERE room_id = ? AND round_number = ?",
        (room_id, room["round_number"]),
    )
    db.execute("UPDATE rooms SET phase = 'voting', round_number = ? WHERE id = ?",
               (room["round_number"] + (room["phase"] == "revealed"), room_id))
    db.commit()
    touch_room(room_id)
    broadcast_room(room_id)
    return jsonify({"room": serialize_room(room_id)})


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/vote")
def submit_vote(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    participant_id = payload.get("participantId")
    participant = participant_in_room(room_id, participant_id)
    if not participant:
        return error("Participant not found in room", 404)

    vote_value = parse_vote_value(payload.get("value"))
    if vote_value is None:
        return error("Vote must be a number or abstain")

    db = get_db()
    room = db.execute(
        "SELECT phase, round_number, deck, auto_reveal FROM rooms WHERE id = ?",
        (room_id,),
    ).fetchone()
    if room["phase"] != "voting":
        return error("Voting has not started")

    abstained = vote_value == "abstain"
    if not abstained:
        if vote_value not in room_deck(room["deck"])["options"]:
            return error("Vote is not available in this room's deck")

    db.execute(
        """
        INSERT INTO votes (participant_id, room_id, round_number, value, abstained)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(participant_id, room_id, round_number)
        DO UPDATE SET value = excluded.value, abstained = excluded.abstained
        """,
        (
            participant_id,
            room_id,
            room["round_number"],
            None if abstained else vote_value,
            1 if abstained else 0,
        ),
    )
    if room["auto_reveal"]:
        reveal_if_everyone_voted(db, room_id, room["round_number"])
    db.commit()
    touch_room(room_id)
    broadcast_room(room_id)
    return jsonify({"room": serialize_room(room_id)})


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/auto-reveal")
def set_auto_reveal(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    participant_id = payload.get("participantId")
    _, leader_error = require_leader(room_id, participant_id)
    if leader_error:
        return leader_error

    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        return error("Enabled must be true or false")

    db = get_db()
    room = db.execute(
        "SELECT phase, round_number FROM rooms WHERE id = ?",
        (room_id,),
    ).fetchone()
    db.execute(
        "UPDATE rooms SET auto_reveal = ? WHERE id = ?",
        (1 if enabled else 0, room_id),
    )
    if enabled and room["phase"] == "voting":
        reveal_if_everyone_voted(db, room_id, room["round_number"])
    db.commit()
    touch_room(room_id)
    broadcast_room(room_id)
    return jsonify({"room": serialize_room(room_id)})


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/reveal")
def reveal_votes(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    participant_id = payload.get("participantId")
    _, leader_error = require_leader(room_id, participant_id)
    if leader_error:
        return leader_error

    db = get_db()
    if db.execute("SELECT phase FROM rooms WHERE id = ?", (room_id,)).fetchone()["phase"] != "voting":
        return error("Voting is not in progress", 409)
    db.execute("UPDATE rooms SET phase = 'revealed' WHERE id = ?", (room_id,))
    db.commit()
    touch_room(room_id)
    broadcast_room(room_id)
    return jsonify({"room": serialize_room(room_id)})


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/restart")
def restart_vote(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    participant_id = payload.get("participantId")
    _, leader_error = require_leader(room_id, participant_id)
    if leader_error:
        return leader_error

    db = get_db()
    room = db.execute("SELECT phase, round_number FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room["phase"] != "revealed":
        return error("Reveal the round before restarting", 409)
    db.execute(
        "DELETE FROM votes WHERE room_id = ? AND round_number = ?",
        (room_id, room["round_number"]),
    )
    db.execute(
        """
        UPDATE rooms
        SET phase = 'lobby', round_number = round_number + 1
        WHERE id = ?
        """,
        (room_id,),
    )
    db.commit()
    touch_room(room_id)
    broadcast_room(room_id)
    return jsonify({"room": serialize_room(room_id)})


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/kick")
def kick_participant(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    leader_id = payload.get("participantId")
    target_id = payload.get("targetParticipantId")
    _, leader_error = require_leader(room_id, leader_id)
    if leader_error:
        return leader_error

    if not target_id:
        return error("Participant is required")

    target = participant_in_room(room_id, target_id)
    if not target:
        return error("Participant not found in room", 404)
    if target["is_leader"]:
        return error("Leader cannot be kicked", 400)

    remove_participant(room_id, target_id)
    check_auto_reveal(room_id)
    touch_room(room_id)
    broadcast_room(room_id)
    return jsonify({"room": serialize_room(room_id)})


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/end")
def end_room(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    participant_id = payload.get("participantId")
    _, leader_error = require_leader(room_id, participant_id)
    if leader_error:
        return leader_error

    remove_room(room_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
