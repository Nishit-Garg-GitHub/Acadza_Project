import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import llm


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def groq_response(content='{"answer":"A"}', model="openai/gpt-oss-120b", finish="stop"):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(
            finish_reason=finish,
            message=types.SimpleNamespace(content=content, refusal=None),
        )],
        model=model,
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


class GroqLive(unittest.TestCase):
    def setUp(self):
        self.captured = {}
        self.responses = [groq_response()]

        class Completions:
            def create(inner, **kwargs):
                self.captured.setdefault("requests", []).append(kwargs)
                response = self.responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return response

        class FakeGroq:
            def __init__(inner, **kwargs):
                self.captured["client"] = kwargs
                inner.chat = types.SimpleNamespace(completions=Completions())

        self.fake_groq = types.SimpleNamespace(Groq=FakeGroq)
        self.patches = [
            patch.object(llm, "PROVIDER", "groq"),
            patch.object(llm, "MODEL", "openai/gpt-oss-120b"),
            patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=True),
            patch.dict(sys.modules, {"groq": self.fake_groq}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_sends_groq_strict_schema_and_parses_response(self):
        client = llm.LLM(mode="live")
        result = client.json("solver", "Q1", "system", "user", SCHEMA)

        request = self.captured["requests"][0]
        self.assertEqual(result, {"answer": "A"})
        self.assertEqual(self.captured["client"]["timeout"], llm.DEFAULT_TIMEOUT)
        self.assertEqual(request["model"], "openai/gpt-oss-120b")
        self.assertEqual(request["max_completion_tokens"], 16000)
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(request["response_format"]["json_schema"]["schema"], SCHEMA)
        self.assertEqual(request["reasoning_effort"], "high")
        self.assertEqual(client.log[0]["provider"], "groq")
        self.assertEqual(client.log[0]["model"], "openai/gpt-oss-120b")
        self.assertEqual(client.log[0]["input_tokens"], 10)

    def test_requires_groq_key_without_echoing_it(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "GROQ_API_KEY is required"):
                llm.LLM(mode="live")

    def test_retries_rate_limit_then_succeeds(self):
        class RateLimitError(Exception):
            status_code = 429

        self.responses = [RateLimitError("sensitive provider detail"), groq_response()]
        with patch.object(llm.time, "sleep"):
            client = llm.LLM(mode="live", retries=1)
            self.assertEqual(client.json("solver", "Q1", "s", "u", SCHEMA), {"answer": "A"})
        self.assertEqual(len(self.captured["requests"]), 2)
        self.assertEqual(client.errors[0]["error"], "groq rate limit exceeded")
        self.assertNotIn("sensitive", str(client.errors))

    def test_authentication_error_is_safe_and_does_not_retry(self):
        class AuthenticationError(Exception):
            status_code = 401

        self.responses = [AuthenticationError("test-key should not be logged")]
        client = llm.LLM(mode="live", retries=2)
        with self.assertRaisesRegex(llm.Unavailable, "authentication failed"):
            client.json("solver", "Q1", "s", "u", SCHEMA)
        self.assertEqual(len(self.captured["requests"]), 1)
        self.assertNotIn("test-key", json.dumps(client.log + client.errors))

    def test_malformed_json_gets_one_controlled_retry(self):
        self.responses = [groq_response("not json"), groq_response()]
        with patch.object(llm.time, "sleep"):
            client = llm.LLM(mode="live", retries=0)
            self.assertEqual(client.json("solver", "Q1", "s", "u", SCHEMA), {"answer": "A"})
        self.assertEqual(len(self.captured["requests"]), 2)
        self.assertEqual(client.log[0]["status"], "invalid_json")

    def test_invalid_schema_response_is_rejected_after_retry(self):
        self.responses = [groq_response('{"other":"A"}'), groq_response('{"other":"A"}')]
        with patch.object(llm.time, "sleep"):
            client = llm.LLM(mode="live", retries=0)
            with self.assertRaisesRegex(llm.Unavailable, "malformed JSON or did not match its schema"):
                client.json("solver", "Q1", "s", "u", SCHEMA)

    def test_nullable_repair_schema_is_normalized_for_groq(self):
        source = {"type": "object", "properties": {
            "repair": {"anyOf": [{"type": "string", "enum": ["answer_key"]}, {"type": "null"}]},
        }, "required": ["repair"], "additionalProperties": False}
        normalized = llm.groq_schema(source)
        self.assertEqual(normalized["properties"]["repair"]["type"], ["string", "null"])
        self.assertEqual(normalized["properties"]["repair"]["enum"], ["answer_key", None])
        llm.validate_json_schema({"repair": None}, source)

    def test_replay_validates_hash_and_output_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            request_digest = llm.request_hash("solver", "s", "u", SCHEMA)
            Path(directory, "solver.json").write_text(json.dumps({
                "Q1": {"request_sha256": request_digest, "output": {"answer": "A"}, "source": "fixture"},
            }), encoding="utf-8")
            client = llm.LLM(mode="replay", replay_dir=directory)
            self.assertEqual(client.json("solver", "Q1", "s", "u", SCHEMA), {"answer": "A"})
            with self.assertRaisesRegex(llm.Unavailable, "stale"):
                client.json("solver", "Q1", "different", "u", SCHEMA)


class AnthropicLive(unittest.TestCase):
    def test_uses_anthropic_structured_output_api(self):
        captured = {}
        response = types.SimpleNamespace(
            stop_reason="end_turn",
            content=[types.SimpleNamespace(type="text", text='{"answer":"A"}')],
            model="claude-test",
            usage=types.SimpleNamespace(input_tokens=8, output_tokens=3),
        )

        class Messages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return response

        def fake_anthropic(**kwargs):
            captured["client"] = kwargs
            return types.SimpleNamespace(beta=types.SimpleNamespace(messages=Messages()))

        with patch.object(llm, "PROVIDER", "anthropic"), \
                patch.object(llm, "MODEL", "claude-test"), \
                patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
                patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=fake_anthropic)}):
            client = llm.LLM(mode="live")
            result = client.json("solver", "Q1", "system", "user", SCHEMA)
        self.assertEqual(result, {"answer": "A"})
        self.assertEqual(captured["model"], "claude-test")
        self.assertEqual(captured["output_config"]["format"]["schema"], SCHEMA)
        self.assertEqual(client.log[0]["provider"], "anthropic")
        self.assertEqual(client.log[0]["input_tokens"], 8)


if __name__ == "__main__":
    unittest.main()
