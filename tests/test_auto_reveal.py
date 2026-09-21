import os
import tempfile
import unittest


_counter_dir = tempfile.TemporaryDirectory()
os.environ["COUNTER_DB_PATH"] = os.path.join(_counter_dir.name, "counter.sqlite3")

from src import app as poker


class AutoRevealTests(unittest.TestCase):
    def setUp(self):
        if hasattr(poker.app, "_db"):
            poker.app._db.close()
            del poker.app._db
        poker.connections.clear()
        self.client = poker.app.test_client()
        self.guest = poker.app.test_client()
        self.addCleanup(setattr, poker, "online_participant_ids", poker.online_participant_ids)

    def api(self, path):
        return f"{poker.BASE_PREFIX}{path}"

    def create_room_with_guest(self):
        created = self.client.post(self.api("/api/rooms"), json={"name": "Leader"}).get_json()
        room_id = created["roomId"]
        joined = self.guest.post(
            self.api(f"/api/rooms/{room_id}/join"), json={"name": "Guest"}
        ).get_json()
        return room_id, created["participantId"], joined["participantId"]

    def test_reveals_after_every_participant_has_voted(self):
        room_id, leader_id, guest_id = self.create_room_with_guest()
        poker.online_participant_ids = lambda current_room: (
            {leader_id, guest_id} if current_room == room_id else set()
        )
        enabled = self.client.post(
            self.api(f"/api/rooms/{room_id}/auto-reveal"),
            json={"participantId": leader_id, "enabled": True},
        )
        self.assertTrue(enabled.get_json()["room"]["autoReveal"])

        self.client.post(
            self.api(f"/api/rooms/{room_id}/start"), json={"participantId": leader_id}
        )
        first_vote = self.client.post(
            self.api(f"/api/rooms/{room_id}/vote"),
            json={"participantId": leader_id, "value": 5},
        )
        self.assertEqual(first_vote.get_json()["room"]["phase"], "voting")

        last_vote = self.guest.post(
            self.api(f"/api/rooms/{room_id}/vote"),
            json={"participantId": guest_id, "value": "abstain"},
        )
        self.assertEqual(last_vote.get_json()["room"]["phase"], "revealed")

    def test_only_leader_can_change_setting(self):
        room_id, _, guest_id = self.create_room_with_guest()
        response = self.guest.post(
            self.api(f"/api/rooms/{room_id}/auto-reveal"),
            json={"participantId": guest_id, "enabled": True},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
