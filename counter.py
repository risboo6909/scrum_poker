"""Persistent aggregate only; room identities and votes never enter this file."""

import sqlite3
from contextlib import closing
from pathlib import Path


class RoomCounter:
    def __init__(self, path, initial_value=0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO counters VALUES ('rooms_created', ?)", (initial_value,))

    def read(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT value FROM counters WHERE name = 'rooms_created'").fetchone()[0]

    def increment(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE counters SET value = value + 1 WHERE name = 'rooms_created'")
