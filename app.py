import json
import os
import sqlite3
import statistics
import threading
import time
import uuid
from contextlib import closing

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_sock import Sock


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
app.total_rooms_created = 0


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
                created_at INTEGER NOT NULL,
                last_activity_at INTEGER NOT NULL
            );

            CREATE TABLE participants (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                name TEXT NOT NULL,
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

    with connections_lock:
        for room_id in expired_ids:
            connections.pop(room_id, None)


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
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value


def serialize_value(value):
    if float(value).is_integer():
        return int(value)
    return float(value)


def normalize_vote_value(value):
    return int(value * 2)


def room_deck(deck_id):
    return DECKS.get(deck_id, DECKS["fibonacci"])


def compute_stats(values):
    if not values:
        return None

    median = statistics.median(values)
    unanimous = len(set(values)) == 1
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

    return {
        "id": room["id"],
        "phase": room["phase"],
        "roundNumber": room["round_number"],
        "deck": deck,
        "participants": serialized_participants,
        "stats": compute_stats(revealed_values) if room["phase"] == "revealed" else None,
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
        total_rooms_created=app.total_rooms_created,
    )


@app.get(f"{BASE_PREFIX}/")
def index():
    return render_index()


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
    if not room_exists(room_id):
        ws.close()
        return

    participant_id = request.args.get("participantId")
    if not participant_id or not participant_in_room(room_id, participant_id):
        ws.close()
        return

    touch_room(room_id)
    add_connection(room_id, participant_id, ws)
    broadcast_room(room_id)

    try:
        ws.send(json.dumps(room_payload(room_id, participant_id)))
        while True:
            message = ws.receive()
            if message is None:
                break
    finally:
        remove_connection(room_id, ws)
        prune_inactive_participants(room_id, keep_voted=True)
        broadcast_room(room_id)


@app.post(f"{BASE_PREFIX}/api/rooms")
def create_room():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    deck_id = "fibonacci"
    if not name:
        return error("Name is required")

    if active_room_count() >= MAX_ACTIVE_ROOMS:
        return error("Room limit reached, please try again later", 503)

    room_id = uuid.uuid4().hex[:8]
    participant_id = uuid.uuid4().hex
    db = get_db()
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
            INSERT INTO participants (id, room_id, name, is_leader, joined_order)
            VALUES (?, ?, ?, 1, 1)
            """,
            (participant_id, room_id, name),
        )
        db.commit()
        app.total_rooms_created += 1

    response = jsonify(
        {
            "roomId": room_id,
            "participantId": participant_id,
            "room": serialize_room(room_id),
        }
    )
    broadcast_room(room_id)
    return response


@app.post(f"{BASE_PREFIX}/api/rooms/<room_id>/join")
def join_room(room_id):
    if not room_exists(room_id):
        return error("Room not found", 404)

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return error("Name is required")

    db = get_db()
    participant_id = uuid.uuid4().hex
    joined_order = (
        db.execute(
            "SELECT COALESCE(MAX(joined_order), 0) + 1 FROM participants WHERE room_id = ?",
            (room_id,),
        ).fetchone()[0]
    )

    db.execute(
        """
        INSERT INTO participants (id, room_id, name, is_leader, joined_order)
        VALUES (?, ?, ?, 0, ?)
        """,
        (participant_id, room_id, name, joined_order),
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
    return response


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

    prune_inactive_participants(room_id, keep_voted=False)
    db = get_db()
    room = db.execute("SELECT round_number FROM rooms WHERE id = ?", (room_id,)).fetchone()
    db.execute(
        "DELETE FROM votes WHERE room_id = ? AND round_number = ?",
        (room_id, room["round_number"]),
    )
    db.execute("UPDATE rooms SET phase = 'voting' WHERE id = ?", (room_id,))
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
        "SELECT phase, round_number, deck FROM rooms WHERE id = ?",
        (room_id,),
    ).fetchone()
    if room["phase"] != "voting":
        return error("Voting has not started")

    abstained = vote_value == "abstain"
    if not abstained:
        allowed_votes = {
            normalize_vote_value(option) for option in room_deck(room["deck"])["options"]
        }
        if normalize_vote_value(vote_value) not in allowed_votes:
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
    room = db.execute("SELECT round_number FROM rooms WHERE id = ?", (room_id,)).fetchone()
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
