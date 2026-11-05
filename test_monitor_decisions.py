import unittest
from monitor_decisions import canonical_video, intake_decision, eligible_recipients, finalize_submission

class DecisionTests(unittest.TestCase):
    def test_youtube_tracking_params(self):
        self.assertEqual(canonical_video("https://youtu.be/rFIiqOiIR4w?t=2"), "youtube:rFIiqOiIR4w")
        self.assertEqual(canonical_video("https://www.youtube.com/shorts/rFIiqOiIR4w"), "youtube:rFIiqOiIR4w")
    def test_tiktok_short_link_not_guessed(self):
        self.assertIsNone(canonical_video("https://vm.tiktok.com/ZPLNBjBwU/"))
    def test_instagram_reel(self):
        self.assertEqual(canonical_video("https://www.instagram.com/reel/Der5t8yOsoK/?igsh=abc"), "instagram:Der5t8yOsoK")
    def test_duplicate_submission(self):
        d=intake_decision("m2","https://youtu.be/rFIiqOiIR4w",set(),{"youtube:rFIiqOiIR4w"})
        self.assertEqual(d["action"],"duplicate")
        self.assertFalse(d["independently_verified"])
    def test_unresolved_not_finalized(self):
        d=intake_decision("m3","https://vm.tiktok.com/ZPLNBjBwU/",set(),set())
        self.assertFalse(finalize_submission(d,True))
    def test_remote_failure_not_finalized(self):
        d=intake_decision("m4","https://youtu.be/rFIiqOiIR4w",set(),set())
        self.assertFalse(finalize_submission(d,False))
    def test_no_unverified_alert(self):
        self.assertEqual(eligible_recipients("youtube:rFIiqOiIR4w",False,{},{}),[])
    def test_partial_delivery(self):
        key="youtube:ABCDEFGHIJK"
        outbox={(key,"jmabray@gmail.com"):"sent"}
        search={(key,"communications@hebronband.org"):False,(key,"admin@hebronband.org"):False}
        self.assertEqual(eligible_recipients(key,True,outbox,search),
            ["communications@hebronband.org","Admin@hebronband.org"])
    def test_unknown_sent_state_fails_closed(self):
        self.assertEqual(eligible_recipients("youtube:ABCDEFGHIJK",True,{},{}),[])
    def test_inflight_prevents_double_send(self):
        key="youtube:ABCDEFGHIJK"
        outbox={(key,"jmabray@gmail.com"):"sending"}
        search={(key,r.lower()):False for r in ("jmabray@gmail.com","communications@hebronband.org","Admin@hebronband.org")}
        self.assertNotIn("jmabray@gmail.com",eligible_recipients(key,True,outbox,search))

if __name__=="__main__":
    unittest.main()
