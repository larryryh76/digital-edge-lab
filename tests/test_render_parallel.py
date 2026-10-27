"""Regression tests for bounded scene rendering and cancellation."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import render_parallel
import pipeline


class ParallelRenderTests(unittest.TestCase):
    def test_two_workers_overlap_and_results_keep_input_order(self):
        lock = threading.Lock()
        active = 0
        peak = 0
        def worker(i, item, cancel, deadline):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.12 if i == 0 else 0.04)
            with lock:
                active -= 1
            return item * 10
        result = render_parallel.run_parallel([0, 1, 2, 3], worker,
                                              max_workers=2, deadline_seconds=3)
        self.assertEqual(result, [0, 10, 20, 30])
        self.assertEqual(peak, 2)

    def test_concurrency_limit_is_respected(self):
        lock = threading.Lock()
        active = peak = 0
        def worker(i, item, cancel, deadline):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return item
        render_parallel.run_parallel(list(range(8)), worker,
                                     max_workers=2, deadline_seconds=3)
        self.assertLessEqual(peak, 2)

    def test_failed_scene_fails_episode(self):
        def worker(i, item, cancel, deadline):
            if item == 2:
                raise RuntimeError("synthetic Blender failure")
            while not cancel.is_set():
                if time.monotonic() > deadline:
                    break
                time.sleep(0.01)
            return item
        with self.assertRaisesRegex(RuntimeError, "scene item 3 failed"):
            render_parallel.run_parallel([0, 1, 2, 3], worker,
                                         max_workers=2, deadline_seconds=2)

    def test_deadline_cancels_cooperative_workers(self):
        stopped = threading.Event()
        def worker(i, item, cancel, deadline):
            while time.monotonic() < deadline and not cancel.is_set():
                time.sleep(0.01)
            stopped.set()
            return item
        with self.assertRaises(TimeoutError):
            render_parallel.run_parallel([0, 1], worker,
                                         max_workers=2, deadline_seconds=0.08)
        self.assertTrue(stopped.is_set())

    def test_diagnostics_json_remains_valid_under_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as d:
            diag = pipeline.Diagnostics(Path(d) / "diagnostics.json")
            threads = [threading.Thread(target=lambda n=n:
                       [diag.append("events", {"thread": n, "i": i})
                        for i in range(20)]) for n in range(6)]
            for t in threads: t.start()
            for t in threads: t.join()
            import json
            data = json.loads((Path(d) / "diagnostics.json").read_text())
            self.assertEqual(len(data["events"]), 40)
            self.assertEqual(len(data["events"]), len(diag.data["events"]))

    def test_actual_encoded_delivery_qa_remains_in_pipeline(self):
        source = (ROOT / "src" / "pipeline.py").read_text()
        self.assertIn("media_qa.delivery_media", source)
        self.assertIn("media_qa.final_motion", source)
        self.assertIn("decide_failures(", source)


if __name__ == "__main__":
    unittest.main()
