"""Gemini REST client with bounded, jittered retry and model rotation.

Run #73 evidence: the pipeline retried a 503 once with a ~0.8s delay, rotated to
another model, hit 429 twice and then fell through to a generic visual path. The
retry policy here is explicit and finite:

  * 429/500/502/503/504 are retried with exponential backoff plus jitter and
    honour `Retry-After` when the API sends it.
  * Non-retryable responses rotate immediately to the next advertised model.
  * A global deadline bounds the whole operation, so a bad day at the API can
    never hang the job or loop forever.
  * Every attempt is recorded (without the key) for diagnostics.
"""

from __future__ import annotations

import json
import random
import time

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
REFUSED_STATUS = {400, 401, 403, 404}
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
MAX_MODELS = 4


class GeminiError(RuntimeError):
    """Raised when generation cannot produce a usable response."""


class GeminiClient:
    def __init__(self, api_key, *, sleep=time.sleep, clock=time.monotonic,
                 session=None, rng=None, log=None):
        if not api_key or not str(api_key).strip():
            raise GeminiError("GEMINI_API_KEY is not configured")
        self.api_key = str(api_key).strip()
        self._sleep = sleep
        self._clock = clock
        self._session = session or requests.Session()
        self._rng = rng or random.Random(20261027)
        self._log = log or (lambda event: None)
        self._models = None
        self.actual_models = {"text": None, "tts": None}
        self.events = []

    # -- diagnostics -------------------------------------------------------
    def _record(self, event):
        event = dict(event)
        self.events.append(event)
        self.events[:] = self.events[-60:]
        self._log(event)

    # -- model discovery ---------------------------------------------------
    def list_models(self, refresh=False):
        if self._models is not None and not refresh:
            return self._models
        try:
            response = self._session.get(
                f"{API_ROOT}/models",
                params={"key": self.api_key, "pageSize": 1000},
                timeout=(5, 20),
            )
            if not response.ok:
                self._record({"stage": "model_discovery", "status": response.status_code})
                self._models = {}
                return self._models
            models = {}
            for item in response.json().get("models", []):
                name = str(item.get("name", "")).removeprefix("models/")
                methods = item.get("supportedGenerationMethods", [])
                if name and "generateContent" in methods:
                    models[name] = methods
            self._models = models
            self._record({"stage": "model_discovery", "status": "ok",
                          "count": len(models)})
            return models
        except (requests.RequestException, ValueError) as exc:
            self._record({"stage": "model_discovery", "status": "error",
                          "detail": str(exc)[:200]})
            self._models = {}
            return self._models

    def candidates(self, configured, audio=False):
        available = self.list_models()
        if audio:
            eligible = [n for n, m in available.items()
                        if "generateContent" in m and "tts" in n.lower()
                        and "image" not in n.lower()]
            priority = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts",
                        "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts")
        else:
            eligible = [n for n, m in available.items()
                        if "generateContent" in m and "flash" in n.lower()
                        and "tts" not in n.lower() and "image" not in n.lower()]
            priority = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
                        "gemini-3.5-flash", "gemini-3-flash-preview",
                        "gemini-3.1-flash-lite-preview", "gemini-3.1-flash-lite",
                        "gemini-3.5-flash-lite", "gemini-flash-latest",
                        "gemini-flash-lite-latest")
        ordered = []
        if configured in eligible:
            ordered.append(configured)
        ordered.extend(name for name in priority if name in eligible and name not in ordered)
        ordered.extend(sorted(name for name in eligible if name not in ordered))
        if not ordered:
            # Model discovery can fail transiently; still allow the configured model.
            ordered = [configured]
        return ordered[:MAX_MODELS]

    # -- generation --------------------------------------------------------
    def generate(self, configured_model, parts, config=None, *,
                 deadline_seconds=180, attempts_per_model=3, label="text"):
        audio = bool(config and "AUDIO" in config.get("responseModalities", []))
        models = self.candidates(configured_model, audio=audio)
        deadline = self._clock() + deadline_seconds
        failures = []
        for model in models:
            for attempt in range(1, attempts_per_model + 1):
                remaining = deadline - self._clock()
                if remaining <= 2:
                    failures.append({"model": model, "status": "deadline_exhausted"})
                    break
                payload = {"contents": [{"parts": parts}]}
                if config:
                    payload["generationConfig"] = config
                response = None
                try:
                    response = self._session.post(
                        f"{API_ROOT}/models/{model}:generateContent",
                        params={"key": self.api_key},
                        json=payload,
                        timeout=(min(6, remaining), min(45, remaining)),
                    )
                except (requests.Timeout, requests.ConnectionError) as exc:
                    status, retryable, detail = "timeout", True, str(exc)[:200]
                except requests.RequestException as exc:
                    status, retryable, detail = "network_error", True, str(exc)[:200]
                else:
                    if response.ok:
                        try:
                            output = response.json()["candidates"][0]["content"]["parts"]
                            if not isinstance(output, list) or not output:
                                raise ValueError("response contained no parts")
                        except (ValueError, KeyError, IndexError, TypeError) as exc:
                            status, retryable, detail = "malformed_response", False, str(exc)[:200]
                        else:
                            self.actual_models[label] = model
                            self._record({"stage": label, "status": "ok", "model": model,
                                          "attempt": attempt})
                            return output
                    else:
                        status = f"http_{response.status_code}"
                        detail = response.text[:240]
                        retryable = response.status_code in RETRYABLE_STATUS
                        retry_after = _retry_after_seconds(response)
                        if retry_after is not None:
                            detail = f"{detail} (retry-after={retry_after})"
                self._record({"stage": label, "status": status, "model": model,
                              "attempt": attempt, "detail": detail})
                failures.append({"model": model, "status": status, "attempt": attempt,
                                 "detail": detail})
                if not retryable or attempt >= attempts_per_model:
                    break
                delay = _backoff_delay(attempt, response, self._rng)
                delay = min(delay, max(0.0, deadline - self._clock() - 1.0))
                if delay <= 0:
                    break
                self._sleep(delay)
        self._record({"stage": label, "status": "exhausted",
                      "models": models, "failures": failures[-8:]})
        raise GeminiError(
            f"{label} generation failed after bounded retries on {models}: "
            + json.dumps(failures[-4:])[:600]
        )


def _retry_after_seconds(response):
    try:
        header = response.headers.get("Retry-After")
    except AttributeError:
        return None
    if not header:
        return None
    try:
        return max(0.0, min(30.0, float(header)))
    except (TypeError, ValueError):
        return None


def _backoff_delay(attempt, response, rng, base=1.0, cap=12.0):
    """Exponential backoff with full jitter, bounded and Retry-After aware."""
    server_hint = _retry_after_seconds(response) if response is not None else None
    window = min(cap, base * (2 ** (attempt - 1)))
    jittered = window * (0.5 + 0.5 * rng.random())
    if server_hint is not None:
        jittered = max(jittered, server_hint)
    return round(min(cap, jittered), 3)
