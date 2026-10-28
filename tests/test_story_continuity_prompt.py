import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pipeline


class StoryContinuityPromptTests(unittest.TestCase):
    def test_relevant_grounded_research_is_passed_to_script_prompt(self):
        memory = {
            "recent_topics": [],
            "running_context": [],
            "channel": {"tone": "curious"},
            "episodes": {},
            "research": [{
                "topic": "Roman roads",
                "findings": "Roman roads connected military, administrative and trading centers.",
                "sources": [{"title": "Museum", "url": "https://example.org/roman-roads"}],
                "verification_status": "grounded_sources_returned_claim_review_still_required"
            }, {
                "topic": "Deep ocean",
                "findings": "Unrelated ocean note.",
                "sources": [{"url": "https://example.org/ocean"}]
            }]
        }
        prompt = pipeline.script_prompt(memory, requested_topic="Roman roads")
        self.assertIn("Roman roads connected military", prompt)
        self.assertIn("https://example.org/roman-roads", prompt)
        self.assertNotIn("Unrelated ocean note", prompt)
        self.assertIn("grounded research notes", prompt)

    def test_prompt_enforces_human_spoken_pacing_and_a_causal_story(self):
        prompt = pipeline.script_prompt({"recent_topics": [], "running_context": [],
                                         "channel": {}, "episodes": {}, "research": []})
        self.assertIn("90-115 spoken words total", prompt)
        self.assertIn("145-160 words per minute", prompt)
        self.assertIn("one human storyteller", prompt)
        self.assertIn("punctuation that gives a voice room to breathe", prompt)
        self.assertIn("Never include stage directions", prompt)

    def test_completed_episode_facts_are_included_in_bounded_prompt(self):
        memory = {
            "recent_topics": [{"topic": "Old topic"}],
            "running_context": ["Legacy continuity note"],
            "channel": {"tone": "curious"},
            "episodes": {"s1e2": {
                "episode_id": "s1e2", "series_id": "rome", "episode_number": 2,
                "title": "The Broken Aqueduct", "status": "completed",
                "summary": "The aqueduct failed after the bridge supports cracked.",
                "characters": [{"id": "marcus", "name": "Marcus"}],
                "ending": "Marcus finds a sealed tunnel.",
                "unresolved": ["Who sealed the tunnel?"],
                "sources": [{"url": "https://example.org/source"}]
            }}
        }
        prompt = pipeline.script_prompt(memory)
        self.assertIn("The Broken Aqueduct", prompt)
        self.assertIn("Who sealed the tunnel?", prompt)
        self.assertIn("Marcus", prompt)
        self.assertIn("CONTINUITY MEMORY", prompt)
        self.assertIn("Avoid recent topics", prompt)


if __name__ == "__main__":
    unittest.main()
