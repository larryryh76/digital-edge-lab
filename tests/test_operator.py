import importlib.util
import tempfile
import unittest
import os
import json
from unittest.mock import patch
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "operator.py"
spec = importlib.util.spec_from_file_location("del_operator", MODULE_PATH)
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


class OperatorTests(unittest.TestCase):
    def test_job_queue_persists_across_connections(self):
        old = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            try:
                operator.connect().close()
                job = operator.job_create("test", "test request")
                loaded = operator.job_get(job["id"])
                self.assertEqual(loaded["status"], "queued")
                self.assertEqual(loaded["instruction"], "test request")
            finally:
                operator.DB_PATH = old

    def test_create_series_persists_and_reports_missing_key(self):
        old_db, old_memory = operator.DB_PATH, operator.MEMORY_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            operator.MEMORY_PATH = Path(temp) / "memory.json"
            operator.MEMORY_PATH.write_text(json.dumps({"channel_name": "Digital Edge Lab",
                "recent_topics": [], "running_context": [], "principles": []}), encoding="utf-8")
            try:
                operator.connect().close()
                with patch.dict(os.environ, {}, clear=True):
                    result = operator.interpret("Create a new series about the fall of ancient Rome")
                self.assertTrue(result["ok"])
                self.assertEqual(result["series"]["title"], "the fall of ancient Rome")
                self.assertEqual(result["job"]["status"], "blocked")
                migrated = json.loads(operator.MEMORY_PATH.read_text(encoding="utf-8"))
                self.assertIn("the-fall-of-ancient-rome", migrated["series"])
            finally:
                operator.DB_PATH, operator.MEMORY_PATH = old_db, old_memory

    def test_unsupported_instruction_is_reported_honestly(self):
        old = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            try:
                result = operator.interpret("Publish my next seven videos publicly")
                self.assertFalse(result["ok"])
                self.assertIn("no safe executor", result["message"])
            finally:
                operator.DB_PATH = old


if __name__ == "__main__":
    unittest.main()
