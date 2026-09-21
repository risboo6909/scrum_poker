from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_auto_reveal import AutoRevealTests, poker


class LifecycleTests(AutoRevealTests):
    def room(self, deck="fibonacci"):
        response = self.client.post(self.api("/api/rooms"), json={"name": "Leader", "deck": deck})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.rid, self.pid = data["roomId"], data["participantId"]
        return data

    def action(self, action, **fields):
        return self.client.post(self.api(f"/api/rooms/{self.rid}/{action}"),
                                json={"participantId": self.pid, **fields})

    def test_identity_cannot_be_spoofed(self):
        self.room()
        self.action("start")
        self.action("vote", value=8)
        public = self.guest.get(self.api(f"/api/rooms/{self.rid}")).get_json()
        self.assertIsNone(public["room"]["participants"][0]["vote"])
        self.assertIsNone(public["viewer"]["currentVote"])
        self.assertNotIn("credential", str(public))
        self.assertEqual(self.guest.get(self.api(f"/api/rooms/{self.rid}?participantId={self.pid}")).status_code, 403)
        for action in ("start", "reveal", "restart", "end", "kick", "vote", "auto-reveal"):
            self.assertEqual(self.guest.post(self.api(f"/api/rooms/{self.rid}/{action}"),
                                            json={"participantId": self.pid}).status_code, 403)
        own = self.client.get(self.api(f"/api/rooms/{self.rid}?participantId={self.pid}")).get_json()
        self.assertEqual(own["viewer"]["currentVote"], 8)

    def test_exact_votes_and_phases_and_rounds(self):
        self.room()
        self.assertEqual(self.action("reveal").status_code, 409)
        self.assertEqual(self.action("vote", value=3).status_code, 400)
        self.assertEqual(self.action("start").get_json()["room"]["roundNumber"], 1)
        self.assertEqual(self.action("start").status_code, 409)
        for value in (3.4, 0, -1, True, "3", "NaN", float("inf"), float("nan"), [], {}):
            self.assertEqual(self.action("vote", value=value).status_code, 400, repr(value))
        self.assertEqual(self.action("vote", value=3).status_code, 200)
        self.assertEqual(self.action("reveal").status_code, 200)
        self.assertEqual(self.action("reveal").status_code, 409)
        self.assertEqual(self.action("start").get_json()["room"]["roundNumber"], 2)
        self.assertEqual(self.action("restart").status_code, 409)
        self.action("reveal")
        self.assertEqual(self.action("restart").get_json()["room"]["roundNumber"], 3)
        self.assertEqual(self.action("start").get_json()["room"]["roundNumber"], 3)

    def test_pu_deck_and_health(self):
        self.room("pu")
        self.action("start")
        self.assertEqual(self.action("vote", value=0.5).status_code, 200)
        self.assertEqual(self.action("vote", value=0.7).status_code, 400)
        self.assertEqual(self.client.get(self.api("/health")).get_json(), {"status": "ok"})
        self.assertEqual(self.client.post(self.api("/api/rooms"), json={"name":"x","deck":"bad"}).status_code, 400)

    def test_kick_unvoted_reveals_and_new_round_retains_option(self):
        self.rid, self.pid, guest = self.create_room_with_guest()
        with patch.object(poker, "online_participant_ids", return_value={self.pid, guest}):
            self.action("auto-reveal", enabled=True)
            self.action("start")
            self.assertEqual(self.action("vote", value=5).get_json()["room"]["phase"], "voting")
            self.assertEqual(self.action("kick", targetParticipantId=guest).get_json()["room"]["phase"], "revealed")
            next_round = self.action("start").get_json()["room"]
            self.assertTrue(next_round["autoReveal"])
            self.assertIsNone(next_round["stats"])

    def test_disconnect_cleanup_reveals(self):
        self.rid, self.pid, guest = self.create_room_with_guest()
        with patch.object(poker, "online_participant_ids", return_value={self.pid, guest}):
            self.action("auto-reveal", enabled=True)
            self.action("start")
            self.action("vote", value=5)
        with poker.state_lock, patch.object(poker, "online_participant_ids", return_value={self.pid}):
            poker.prune_inactive_participants(self.rid, keep_voted=True)
            poker.check_auto_reveal(self.rid)
            self.assertEqual(poker.serialize_room(self.rid)["phase"], "revealed")

    def test_default_off_and_enable_completed_vote(self):
        self.room()
        self.action("start")
        self.assertEqual(self.action("vote", value=5).get_json()["room"]["phase"], "voting")
        self.assertEqual(self.action("auto-reveal", enabled=True).get_json()["room"]["phase"], "revealed")

    def test_stats_and_confetti(self):
        self.assertEqual(poker.compute_stats([3,3,5,5])["median"],4)
        self.assertEqual(poker.compute_stats([3,3,5,5])["mode"],3)
        self.assertIsNone(poker.compute_stats([]))
        self.assertFalse(poker.compute_stats([8])["unanimous"])
        self.assertTrue(poker.compute_stats([8,8])["unanimous"])

    def test_capacity_under_concurrent_creation(self):
        def create(_):
            return poker.app.test_client().post(self.api("/api/rooms"), json={"name":"Concurrent"}).status_code
        with patch.object(poker, "MAX_ACTIVE_ROOMS", 4), ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(create, range(12)))
        self.assertEqual(statuses.count(200),4)
        self.assertEqual(statuses.count(503),8)

    def test_concurrent_final_votes(self):
        self.rid, self.pid, guest_id = self.create_room_with_guest()
        with patch.object(poker, "online_participant_ids", return_value={self.pid, guest_id}):
            self.action("auto-reveal", enabled=True)
            self.action("start")
            def vote(pair):
                client, participant = pair
                return client.post(self.api(f"/api/rooms/{self.rid}/vote"),
                                   json={"participantId":participant, "value":8}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(vote, [(self.client,self.pid),(self.guest,guest_id)])),[200,200])
            room = self.client.get(self.api(f"/api/rooms/{self.rid}")).get_json()["room"]
            self.assertEqual(room["phase"],"revealed")
            self.assertTrue(room["stats"]["unanimous"])

    def test_websocket_private_session_and_origin(self):
        self.room()
        self.action("start")
        self.action("vote",value=8)
        class Socket:
            def __init__(self): self.messages=[]; self.closed=False
            def send(self, data): self.messages.append(data)
            def receive(self): return None
            def close(self): self.closed=True
        path = self.api(f"/ws/rooms/{self.rid}?participantId={self.pid}")
        cookie = self.client.get_cookie(poker.cookie_name(self.rid),path=f"{poker.BASE_PREFIX}/")
        for headers, allowed in [({},False), ({"Cookie": f"{cookie.key}={cookie.value}"},True),
                                 ({"Cookie":f"{cookie.key}={cookie.value}","Origin":"https://other.example"},False)]:
            socket=Socket()
            with poker.app.test_request_context(path,headers=headers):
                poker.handle_room_socket(socket,self.rid)
            self.assertEqual(bool(socket.messages),allowed)
            if allowed:
                self.assertEqual(poker.json.loads(socket.messages[0])["viewer"]["currentVote"],8)

    def test_abstention_prevents_confetti(self):
        self.rid,self.pid,guest_id=self.create_room_with_guest()
        with patch.object(poker,"online_participant_ids",return_value={self.pid,guest_id}):
            self.action("start")
            self.action("vote",value=8)
            self.guest.post(self.api(f"/api/rooms/{self.rid}/vote"),json={"participantId":guest_id,"value":"abstain"})
            self.assertFalse(self.action("reveal").get_json()["room"]["stats"]["unanimous"])

    def test_expiry_removes_votes_and_participants(self):
        self.room()
        self.action("start")
        self.action("vote", value=3)
        with poker.state_lock:
            db = poker.get_db()
            db.execute("UPDATE rooms SET last_activity_at = 0")
            db.commit()
        self.assertEqual(self.client.get(self.api(f"/api/rooms/{self.rid}")).status_code,404)
        for table in ("rooms", "participants", "votes"):
            self.assertEqual(poker.get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],0)
