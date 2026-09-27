"""Regressions based on verified Hebron videos and prior false-positive reports."""
import unittest
from candidate_rules import triage_video


CONFIG = {
    "negative_terms": ["church", "worship", "prayer", "volleyball", "soccer"],
    "other_school_terms": ["Klein Collins High School", "Klein Forest High School"],
}
CONFIRMED_CHANNEL = "UCZN36ExAXDgUqveVmCqm5Ig"


def classify(title, score=9, description="", channel="unknown", tags=None):
    snippet = {"title": title, "description": description, "channelId": channel,
               "tags": tags or []}
    return triage_video(snippet, CONFIG, score, {CONFIRMED_CHANNEL},
                        ["Melissa", "Kenny Deel"], 7, 4)[0]


class RealWorldHebronCases(unittest.TestCase):
    def test_new_user_reported_melissa_video_is_relevant(self):
        self.assertEqual(classify("Hebron HS Marching Band - Melissa Marching Showcase 2026", 12,
                                  channel=CONFIRMED_CHANNEL), "alert")

    def test_original_confirmed_full_show_reference(self):
        self.assertEqual(classify("Hebron 2026 Exposed Full Show leak", 9), "alert")

    def test_prior_false_positive_football_stream(self):
        self.assertEqual(classify("Live Hebron vs Little Elm - High School Football", 9,
                                  description="Join our game stream 2026"), "ignore")

    def test_prior_false_positive_other_marching_band(self):
        self.assertEqual(classify("Klein Collins High School Marching Band vs Klein Forest",
                                  9, description="Danny Elfman"), "ignore")

    def test_prior_false_positive_church(self):
        self.assertEqual(classify("Hebron Church Sunday Worship 2026", 12), "ignore")

    def test_vague_video_from_confirmed_uploader_requires_review(self):
        self.assertEqual(classify("Melissa yesterday", 3,
                                  channel=CONFIRMED_CHANNEL), "review")

    def test_unrelated_video_from_confirmed_uploader_not_flagged(self):
        self.assertEqual(classify("My Sunday breakfast", 3,
                                  channel=CONFIRMED_CHANNEL), "ignore")

    def test_generic_event_spectator_video_requires_review(self):
        self.assertEqual(classify("Melissa marching showcase spectator video", 4), "review")

    def test_show_title_without_school_requires_review(self):
        self.assertEqual(classify("Somewhere in Time marching band 2026", 8), "review")

    def test_show_music_without_school_band_context_not_alerted(self):
        self.assertEqual(classify("Somewhere in Time John Barry original soundtrack", 10), "ignore")

    def test_score_alone_never_confirms_identity(self):
        self.assertEqual(classify("Texas football live 2026", 20), "ignore")


if __name__ == "__main__":
    unittest.main()
