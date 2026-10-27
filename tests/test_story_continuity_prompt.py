import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pipeline


class StoryContinuityPromptTests(unittest.TestCase):
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
