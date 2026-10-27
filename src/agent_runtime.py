"""Bounded model-backed tool-calling agent for Digital Edge Lab.

Uses Gemini's native function-calling protocol. Tools are executed locally only after
schema validation, and the model must observe their real JSON results before continuing.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Any

import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_ROUNDS = 5
MAX_HISTORY = 16

TOOL_DECLARATIONS = [
    {"name": "list_jobs", "description": "Read persistent production jobs and their actual status, stage, errors, and results.",
     "parameters": {"type": "OBJECT", "properties": {"limit": {"type": "INTEGER", "minimum": 1, "maximum": 50}}}},
    {"name": "get_channel_memory", "description": "Read saved channel identity, series, completed episodes, continuity, research and publishing records.",
     "parameters": {"type": "OBJECT", "properties": {"series_id": {"type": "STRING"}}}},
    {"name": "research_topic", "description": "Research a topic with Gemini Google Search grounding. Store the returned findings and grounded source URLs in channel memory. This is source-backed research, not proof that every claim is independently verified.",
     "parameters": {"type": "OBJECT", "properties": {"topic": {"type": "STRING"}}, "required": ["topic"]}},
    {"name": "start_episode", "description": "Start a real Gemini-to-narration-to-Blender episode pipeline for a topic. Use continue_existing=true to continue the chosen or latest active series.",
     "parameters": {"type": "OBJECT", "properties": {
         "topic": {"type": "STRING", "description": "Specific episode topic or series subject"},
         "series_id": {"type": "STRING", "description": "Existing series ID; optional when continuing latest active series"},
         "continue_existing": {"type": "BOOLEAN", "description": "Continue an existing series instead of creating a new series"}
     }, "required": ["topic", "continue_existing"]}},
    {"name": "run_offline_pilot", "description": "Run the actual deterministic offline production pipeline. Returns a persisted job ID; does not claim success before completion.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "diagnose_recent_failures", "description": "Inspect stored failed/cancelled/blocked jobs and their actual error logs.",
     "parameters": {"type": "OBJECT", "properties": {"limit": {"type": "INTEGER", "minimum": 1, "maximum": 20}}}},
    {"name": "inspect_latest_artifact", "description": "Inspect the actual latest pipeline report and local media files; never infer video validity from a job exit alone.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "prepare_tiktok_manual_upload", "description": "Package the latest QA-passed MP4 for manual TikTok upload when API authorization is unavailable. Does not publish.",
     "parameters": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}} , "required": ["title"]}},
    {"name": "upload_youtube_private", "description": "Upload the latest QA-passed MP4 to the user's authorized YouTube account as PRIVATE only. Requires configured OAuth client/token and explicit user request. Never makes it public.",
     "parameters": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "description": {"type": "STRING"}} , "required": ["title"]}}
]

def _contents(history, message):
    items = []
    for entry in history[-MAX_HISTORY:]:
        role = entry.get("role")
        text = str(entry.get("message", "")).strip()
        if role not in ("user", "assistant") or not text:
            continue
        items.append({"role": "user" if role == "user" else "model", "parts": [{"text": text[:4000]}]})
    items.append({"role": "user", "parts": [{"text": message[:8000]}]})
    return items

def _validate_arguments(name: str, args: Any) -> dict:
    spec = next((x for x in TOOL_DECLARATIONS if x["name"] == name), None)
    if not spec:
        raise ValueError("Model requested an unregistered tool: " + str(name))
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object")
    schema = spec.get("parameters", {})
    props = schema.get("properties", {})
    required = schema.get("required", [])
    if set(args) - set(props):
        raise ValueError("Unexpected tool argument(s): " + ", ".join(sorted(set(args) - set(props))))
    for key in required:
        if key not in args:
            raise ValueError("Missing required tool argument: " + key)
    for key, value in args.items():
        kind = props[key].get("type")
        if kind == "STRING" and not isinstance(value, str):
            raise ValueError(key + " must be a string")
        if kind == "BOOLEAN" and not isinstance(value, bool):
            raise ValueError(key + " must be a boolean")
        if kind == "INTEGER" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(key + " must be an integer")
        if kind == "INTEGER":
            if "minimum" in props[key] and value < props[key]["minimum"]:
                raise ValueError(key + " is below its minimum")
            if "maximum" in props[key] and value > props[key]["maximum"]:
                raise ValueError(key + " exceeds its maximum")
    return args

class AgentError(RuntimeError):
    pass

class GeminiToolAgent:
    """Small bounded Gemini function-calling loop with an injectable HTTP session for tests."""
    def __init__(self, api_key=None, model=None, session=None, max_rounds=MAX_TOOL_ROUNDS):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("DEL_AGENT_MODEL", DEFAULT_MODEL)
        self.session = session or requests.Session()
        self.max_rounds = max(1, min(MAX_TOOL_ROUNDS, int(max_rounds)))

    def _call_model(self, contents):
        if not self.api_key:
            raise AgentError("AI agent is unavailable: GEMINI_API_KEY is missing. No model reasoning or tool execution occurred.")
        url = f"{API_ROOT}/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text":
                "You are Digital Edge Lab's channel-operator agent. Understand natural language, plan carefully, "
                "and use the registered tools for any claims about local jobs, memory, files, production or publishing. "
                "Observe tool results and decide the next action. Never claim an action succeeded unless its tool result "
                "proves it. Do not invent sources, analytics, progress, model access or publication. Ask for clarification "
                "if an essential topic is missing. Public publishing is forbidden; only the private-upload tool exists. "
                "A tool can start a background job, which is not the same as completing it. Be concise and transparent."}]},
            "contents": contents,
            "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1600}
        }
        try:
            response = self.session.post(url, params={"key": self.api_key}, json=payload, timeout=(8, 45))
        except requests.RequestException as exc:
            raise AgentError("Gemini request failed before a model response: " + str(exc)[:240]) from exc
        if response.status_code >= 400:
            detail = getattr(response, "text", "")[:350]
            raise AgentError(f"Gemini API returned HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
            candidate = data["candidates"][0]
            content = candidate["content"]
            parts = content["parts"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentError("Gemini returned a malformed or empty response.") from exc
        return content, parts

    def run(self, message: str, history: list[dict], execute_tool: Callable[[str, dict], Any]) -> dict:
        contents = _contents(history, message)
        executed = []
        for _round in range(self.max_rounds):
            model_content, parts = self._call_model(contents)
            calls = [p["functionCall"] for p in parts if isinstance(p, dict) and isinstance(p.get("functionCall"), dict)]
            if not calls:
                answer = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")).strip()
                if not answer:
                    raise AgentError("Gemini returned neither a final text answer nor a usable tool call.")
                return {"ok": True, "message": answer, "model": self.model, "provider": "Google Gemini",
                        "tool_calls": executed, "turns": len(executed)}
            contents.append(model_content)
            for call in calls:
                name = str(call.get("name", ""))
                args = {}
                try:
                    args = _validate_arguments(name, call.get("args", {}))
                    result = execute_tool(name, args)
                    envelope = {"ok": True, "result": result}
                except Exception as exc:
                    envelope = {"ok": False, "error": str(exc)[:1200], "tool": name}
                executed.append({"name": name, "arguments": args if "args" in locals() else {},
                                 "ok": envelope["ok"], "result": envelope.get("result") if envelope["ok"] else None,
                                 "error": envelope.get("error")})
                contents.append({"role": "user", "parts": [{"functionResponse": {
                    "name": name, "response": envelope
                }}]})
        # Ask for a final evidence-based summary after the bounded action budget.
        contents.append({"role": "user", "parts": [{"text":
            "Tool-call budget reached. Summarize only what the returned tool results establish, "
            "state unfinished jobs as unfinished, and do not start additional tools."}]})
        model_content, parts = self._call_model(contents)
        answer = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")).strip()
        if not answer:
            answer = "The action limit was reached. Tool results are available in the job history; no additional action was taken."
        return {"ok": True, "message": answer, "model": self.model, "provider": "Google Gemini",
                "tool_calls": executed, "turns": len(executed), "action_limit_reached": True}
