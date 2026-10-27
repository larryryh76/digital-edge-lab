import unittest

from agent_runtime import AgentError, GeminiToolAgent


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def response(parts):
    return {"candidates": [{"content": {"role": "model", "parts": parts}}]}


class GeminiToolAgentTests(unittest.TestCase):
    def test_model_calls_real_tool_and_observes_result_before_final_answer(self):
        session = FakeSession([
            response([{"functionCall": {"name": "list_jobs", "args": {"limit": 2}}}]),
            response([{"text": "I checked the stored jobs. One is queued and none is completed."}])
        ])
        executed = []
        def execute(name, args):
            executed.append((name, args))
            return {"jobs": [{"id": "job-1", "status": "queued"}]}
        agent = GeminiToolAgent(api_key="test-key", model="gemini-2.5-flash", session=session)
        result = agent.run("What is the status?", [], execute)
        self.assertTrue(result["ok"])
        self.assertIn("One is queued", result["message"])
        self.assertEqual(executed, [("list_jobs", {"limit": 2})])
        self.assertEqual(len(session.calls), 2)
        followup = session.calls[1][1]["json"]["contents"]
        self.assertTrue(any("functionResponse" in part for item in followup
                            for part in item.get("parts", [])))
        self.assertEqual(result["tool_calls"][0]["result"], {"jobs": [{"id": "job-1", "status": "queued"}]})

    def test_invalid_tool_arguments_are_returned_as_failure_not_executed(self):
        session = FakeSession([
            response([{"functionCall": {"name": "list_jobs", "args": {"limit": 2, "delete_all": True}}}]),
            response([{"text": "I could not run that tool call because its arguments were invalid."}])
        ])
        executed = []
        result = GeminiToolAgent(api_key="test-key", session=session).run(
            "Check jobs", [], lambda name, args: executed.append((name, args)))
        self.assertEqual(executed, [])
        self.assertFalse(result["tool_calls"][0]["ok"])
        self.assertIn("Unexpected tool argument", result["tool_calls"][0]["error"])

    def test_missing_key_is_a_hard_blocker(self):
        with self.assertRaisesRegex(AgentError, "GEMINI_API_KEY is missing"):
            GeminiToolAgent(api_key="").run("hello", [], lambda name, args: None)


if __name__ == "__main__":
    unittest.main()
