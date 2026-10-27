import importlib.util
import tempfile
import unittest
import os
import json
from unittest.mock import patch
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "channel_operator.py"
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

    def test_job_summaries_keep_errors_bounded_and_drop_full_log_tails(self):
        summary = operator._safe_job_summary({
            "id": "job-1", "kind": "offline_pilot", "status": "failed",
            "stage": "failed", "error": "actual error",
            "result": {"exit_code": 1, "log_tail": "x" * 20000}
        })
        self.assertEqual(summary["error"], "actual error")
        self.assertNotIn("log_tail", summary["result"])
        self.assertEqual(summary["result"]["exit_code"], 1)

    def test_conversation_survives_separate_database_connections(self):
        old = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "operator.sqlite3"
            try:
                operator.conversation("user", "Remember this instruction.")
                operator.connect().close()
                history = operator.recent_conversation()
                self.assertEqual(history[-1]["role"], "user")
                self.assertEqual(history[-1]["message"], "Remember this instruction.")
            finally:
                operator.DB_PATH = old

    def test_missing_model_key_is_not_misrepresented_as_ai(self):
        old = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            try:
                operator.connect().close()
                with patch.dict(os.environ, {}, clear=True):
                    result = operator.interpret("Create a new series about the fall of ancient Rome")
                self.assertFalse(result["ok"])
                self.assertIn("GEMINI_API_KEY is missing", result["message"])
                self.assertEqual(result["tool_calls"], [])
            finally:
                operator.DB_PATH = old

    def test_real_tool_executor_persists_series_and_reports_missing_key(self):
        old_db, old_memory = operator.DB_PATH, operator.MEMORY_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            operator.MEMORY_PATH = Path(temp) / "memory.json"
            try:
                operator.connect().close()
                with patch.dict(os.environ, {}, clear=True):
                    result = operator._agent_tool("start_episode", {
                        "topic": "The fall of ancient Rome", "continue_existing": False})
                self.assertTrue(result["blocked"])
                self.assertEqual(result["job"]["status"], "blocked")
                migrated = json.loads(operator.MEMORY_PATH.read_text(encoding="utf-8"))
                self.assertIn("the-fall-of-ancient-rome", migrated["series"])
            finally:
                operator.DB_PATH, operator.MEMORY_PATH = old_db, old_memory

    def test_missing_model_key_does_not_claim_publishing_completed(self):
        old = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            try:
                with patch.dict(os.environ, {}, clear=True):
                    result = operator.interpret("Publish my next seven videos publicly")
                self.assertFalse(result["ok"])
                self.assertIn("GEMINI_API_KEY is missing", result["message"])
            finally:
                operator.DB_PATH = old

    def test_model_cancel_tool_cancels_queued_job(self):
        old_db = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            try:
                job = operator.job_create("offline_pilot", "pilot")
                result = operator._agent_tool("cancel_job", {"job_id": job["id"]})
                self.assertTrue(result["cancelled"])
                self.assertEqual(operator.job_get(job["id"])["status"], "cancelled")
            finally:
                operator.DB_PATH = old_db

    def test_model_retry_tool_creates_separate_retry_without_overwriting_old_logs(self):
        old_db = operator.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            operator.DB_PATH = Path(temp) / "jobs.sqlite3"
            try:
                failed = operator.job_create("offline_pilot", "pilot", status="failed", stage="failed")
                operator.update_job(failed["id"], error="original failure evidence")
                class FakeThread:
                    def __init__(self, **kwargs):
                        self.kwargs = kwargs
                    def start(self):
                        pass
                with patch.object(operator.threading, "Thread", FakeThread):
                    result = operator._agent_tool("retry_job", {"job_id": failed["id"]})
                self.assertTrue(result["retry_started"])
                self.assertNotEqual(result["job"]["id"], failed["id"])
                self.assertEqual(operator.job_get(failed["id"])["error"], "original failure evidence")
                self.assertEqual(result["job"]["status"], "retrying")
            finally:
                operator.DB_PATH = old_db

    def test_latest_artifact_requires_report_and_nonempty_mp4(self):
        old_root = operator.ROOT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            delivery = root / "output" / "delivery"
            delivery.mkdir(parents=True)
            video = delivery / "pilot.mp4"
            video.write_bytes(b"not a real encoded MP4, path resolution test only")
            report = root / "output" / "run-report.json"
            report.write_text(json.dumps({"status": "verified_delivery",
                "video_file": "output/delivery/pilot.mp4"}), encoding="utf-8")
            operator.ROOT = root
            try:
                path, loaded = operator._latest_verified_video()
                self.assertEqual(path, video.resolve())
                self.assertEqual(loaded["status"], "verified_delivery")
                video.unlink()
                with self.assertRaisesRegex(RuntimeError, "missing or empty"):
                    operator._latest_verified_video()
            finally:
                operator.ROOT = old_root


if __name__ == "__main__":
    unittest.main()
