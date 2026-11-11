from unittest.mock import patch

from tests.test_auto_reveal import AutoRevealTests, poker


class SpectatorTests(AutoRevealTests):
    def test_spectator_observes_but_cannot_vote_or_count_as_voter(self):
        room_id, leader_id, guest_id = self.create_room_with_guest()
        spectator = poker.app.test_client()
        joined = spectator.post(self.api(f"/api/rooms/{room_id}/join"),
                                json={"name": "Observer", "spectator": True}).get_json()
        spectator_id = joined["participantId"]
        observer = next(p for p in joined["room"]["participants"] if p["id"] == spectator_id)
        self.assertTrue(observer["isSpectator"])
        with patch.object(poker, "online_participant_ids", return_value={leader_id, spectator_id}):
            self.assertEqual(self.client.post(self.api(f"/api/rooms/{room_id}/start"),
                                             json={"participantId": leader_id}).status_code, 409)
        with patch.object(poker, "online_participant_ids", return_value={leader_id, guest_id, spectator_id}):
            self.client.post(self.api(f"/api/rooms/{room_id}/auto-reveal"), json={"participantId": leader_id, "enabled": True})
            self.client.post(self.api(f"/api/rooms/{room_id}/start"), json={"participantId": leader_id})
            self.assertEqual(spectator.post(self.api(f"/api/rooms/{room_id}/vote"), json={"participantId": spectator_id, "value": 5}).status_code, 403)
            self.client.post(self.api(f"/api/rooms/{room_id}/vote"), json={"participantId": leader_id, "value": 5})
            result = self.guest.post(self.api(f"/api/rooms/{room_id}/vote"), json={"participantId": guest_id, "value": 5}).get_json()["room"]
            self.assertEqual(result["phase"], "revealed")
            self.assertTrue(result["stats"]["unanimous"])
            observed = spectator.get(self.api(f"/api/rooms/{room_id}?participantId={spectator_id}")).get_json()
            self.assertEqual(observed["room"]["stats"]["median"], 5)
            self.assertTrue(observed["viewer"]["isSpectator"])

    def test_invalid_spectator_flag_is_rejected(self):
        created = self.client.post(self.api("/api/rooms"), json={"name": "Leader"}).get_json()
        response = self.guest.post(self.api(f"/api/rooms/{created['roomId']}/join"), json={"name": "Guest", "spectator": "yes"})
        self.assertEqual(response.status_code, 400)
