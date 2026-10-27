"""Bounded-retry behaviour for 429/503 responses (run #73 hit 503 then 429)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import random  # noqa: E402

from gemini_client import GeminiClient, GeminiError, _backoff_delay  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 4))
        self.now += seconds


class FakeResponse:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text or ("" if payload is None else str(payload))
        self.ok = 200 <= status < 300

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


GOOD = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
MODEL_LIST = {"models": [
    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.7-flash", "supportedGenerationMethods": ["generateContent"]},
]}


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.posts = []

    def get(self, url, params=None, timeout=None, **kwargs):
        return FakeResponse(200, MODEL_LIST)

    def post(self, url, params=None, json=None, timeout=None, **kwargs):
        self.posts.append(url)
        action = self.script.pop(0) if self.script else FakeResponse(503, None, text="{}")
        return action


def build(script, clock=None):
    clock = clock or FakeClock()
    client = GeminiClient("test-key", sleep=clock.sleep, clock=clock.clock,
                          session=FakeSession(script), rng=random.Random(7))
    return client, clock


class RetryTests(unittest.TestCase):
    def test_503_then_success_is_retried(self):
        client, clock = build([FakeResponse(503, None, text="{}"), FakeResponse(200, GOOD)])
        parts = client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=60)
        self.assertEqual(parts[0]["text"], "ok")
        self.assertEqual(len(clock.sleeps), 1)
        self.assertGreater(clock.sleeps[0], 0)

    def test_429_is_retried_with_backoff_growth(self):
        client, clock = build([
            FakeResponse(429, None, text="{}"),
            FakeResponse(429, None, text="{}"),
            FakeResponse(200, GOOD),
        ])
        client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=120)
        self.assertEqual(len(clock.sleeps), 2)
        self.assertGreater(clock.sleeps[1], clock.sleeps[0])

    def test_retry_after_is_honoured(self):
        client, clock = build([
            FakeResponse(429, None, headers={"Retry-After": "3"}, text="{}"),
            FakeResponse(200, GOOD),
        ])
        client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=120)
        self.assertGreaterEqual(clock.sleeps[0], 3.0)

    def test_exhaustion_is_bounded_and_never_infinite(self):
        clock = FakeClock()
        client, _ = build([FakeResponse(503, None, text="{}")] * 40, clock=clock)
        with self.assertRaises(GeminiError):
            client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=600,
                            attempts_per_model=3)
        # 2 advertised models x 3 attempts, and no more.
        self.assertEqual(len(client._session.posts), 6)
        self.assertLessEqual(len(clock.sleeps), 6)

    def test_deadline_bounds_total_time(self):
        clock = FakeClock()
        client, _ = build([FakeResponse(503, None, text="{}")] * 40, clock=clock)
        with self.assertRaises(GeminiError):
            client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=5,
                            attempts_per_model=3)
        self.assertLessEqual(clock.now, 6.0)

    def test_non_retryable_error_rotates_to_next_model(self):
        client, clock = build([FakeResponse(400, None, text="bad request"),
                               FakeResponse(200, GOOD)])
        client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=60)
        self.assertEqual(len(client._session.posts), 2)
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(client.actual_models["text"], "gemini-3.7-flash")

    def test_malformed_response_is_not_retried_forever(self):
        client, _ = build([FakeResponse(200, {"candidates": []})] * 10)
        with self.assertRaises(GeminiError):
            client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=60)

    def test_timeout_is_retried_then_rotated(self):
        import requests

        class TimeoutSession(FakeSession):
            def post(self, *args, **kwargs):
                self.posts.append("timeout")
                raise requests.Timeout("too slow")

        client = GeminiClient("k", sleep=lambda s: None, clock=lambda: 0.0,
                              session=TimeoutSession([]), rng=random.Random(1))
        with self.assertRaises(GeminiError):
            client.generate("gemini-3.8-flash", [{"text": "hi"}], deadline_seconds=60,
                            attempts_per_model=2)
        self.assertEqual(len(client._session.posts), 4)

    def test_missing_key_fails_loudly(self):
        with self.assertRaises(GeminiError):
            GeminiClient("")

    def test_backoff_is_capped(self):
        rng = random.Random(0)
        self.assertLessEqual(_backoff_delay(9, None, rng), 12.0)


if __name__ == "__main__":
    unittest.main()
