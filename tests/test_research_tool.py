import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import channel_operator


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"candidates": [{
            "content": {"parts": [{"text": "Roman roads linked military posts and settlements."}]},
            "groundingMetadata": {"groundingChunks": [
                {"web": {"title": "Museum research", "uri": "https://example.org/roman-roads"}},
                {"web": {"title": "Museum research", "uri": "https://example.org/roman-roads"}}
            ]}
        }]}


class GroundedResearchTests(unittest.TestCase):
    def test_research_saves_grounding_urls_and_deduplicates(self):
        old_memory = channel_operator.MEMORY_PATH
        with tempfile.TemporaryDirectory() as temp:
            channel_operator.MEMORY_PATH = Path(temp) / "memory.json"
            try:
                with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True), \
                     patch("requests.post", return_value=FakeResponse()) as post:
                    first = channel_operator._research_topic("Roman roads")
                    second = channel_operator._research_topic("Roman roads")
                self.assertFalse(first["duplicate_prevented"])
                self.assertTrue(second["duplicate_prevented"])
                self.assertEqual(first["research"]["sources"], [
                    {"title": "Museum research", "url": "https://example.org/roman-roads"}])
                self.assertEqual(len(json.loads(channel_operator.MEMORY_PATH.read_text())["research"]), 1)
                self.assertEqual(post.call_count, 2)
            finally:
                channel_operator.MEMORY_PATH = old_memory

    def test_research_refuses_to_save_without_grounding_sources(self):
        old_memory = channel_operator.MEMORY_PATH
        with tempfile.TemporaryDirectory() as temp:
            channel_operator.MEMORY_PATH = Path(temp) / "memory.json"
            try:
                response = FakeResponse()
                response.json = lambda: {"candidates": [{
                    "content": {"parts": [{"text": "Some claims without grounding."}],
                    "groundingMetadata": {"groundingChunks": []}
                }]}
                with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True), \
                     patch("requests.post", return_value=response):
                    with self.assertRaisesRegex(RuntimeError, "source URLs"):
                        channel_operator._research_topic("Unverified topic")
                self.assertFalse(channel_operator.MEMORY_PATH.exists())
            finally:
                channel_operator.MEMORY_PATH = old_memory


if __name__ == "__main__":
    unittest.main()
