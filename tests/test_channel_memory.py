import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from channel_memory import ChannelMemory


class ChannelMemoryTests(unittest.TestCase):
    def test_legacy_memory_migrates_without_losing_topics_or_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.json"
            path.write_text(json.dumps({"channel_name": "Digital Edge Lab",
                "principles": ["no fabricated claims"],
                "recent_topics": [{"title": "Old", "topic": "Existing topic"}],
                "running_context": ["Keep continuity"]}), encoding="utf-8")
            memory = ChannelMemory(path)
            migrated = memory.load()
            self.assertEqual(migrated["schema_version"], 2)
            self.assertEqual(migrated["recent_topics"][0]["topic"], "Existing topic")
            self.assertEqual(migrated["channel"]["editorial_rules"], ["no fabricated claims"])
            memory.save(migrated)
            self.assertTrue(path.exists())
            self.assertEqual(memory.load()["recent_topics"][0]["title"], "Old")

    def test_episode_idempotency_and_qa_gated_memory_update(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = ChannelMemory(Path(temp) / "memory.json")
            memory.create_episode("s1-e1", title="Pilot", topic="Continuity", series_id="s1")
            with self.assertRaises(ValueError):
                memory.create_episode("s1-e1", title="Duplicate", topic="Continuity", series_id="s1")
            with self.assertRaises(ValueError):
                memory.complete_episode("s1-e1", {"status": "failed_qa"})
            done = memory.complete_episode("s1-e1", {"status": "verified_delivery", "summary": "Passed"})
            self.assertEqual(done["status"], "completed")
            self.assertEqual(memory.context_for("s1")["episodes"][0]["summary"], "Passed")


if __name__ == "__main__":
    unittest.main()
