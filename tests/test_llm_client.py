"""LLM JSON 客户端测试（Fake Chat，不访问网络）。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from pydantic import BaseModel

from app.config import Settings
from app.llm.client import LLMClient, LLMError, parse_json_object


class _SimpleModel(BaseModel):
    ok: bool
    value: str = ""


class _FakeChat:
    def __init__(self, content: str | Exception) -> None:
        self.content = content

    def bind(self, **kwargs):
        return self

    def invoke(self, messages):
        if isinstance(self.content, Exception):
            raise self.content
        return SimpleNamespace(content=self.content)


class TestLLMClient(unittest.TestCase):
    def _settings(self) -> Settings:
        return Settings(_env_file=None, llm_api_key="test-key")

    def test_parse_json_object_with_fence(self) -> None:
        data = parse_json_object('```json\n{"ok": true}\n```')
        self.assertEqual(data, {"ok": True})

    def test_generate_json_and_unwrap(self) -> None:
        client = LLMClient(
            self._settings(),
            models=["fake"],
            chat_factory=lambda model: _FakeChat(
                '{"markdown": "{\\"ok\\": true, \\"value\\": \\"nested\\"}"}'
            ),
        )
        result, model = client.generate_json("sys", "user", _SimpleModel)
        self.assertTrue(result.ok)
        self.assertEqual(result.value, "nested")
        self.assertEqual(model, "fake")

    def test_repair_after_invalid_json(self) -> None:
        responses = iter(
            [
                "not json",
                '{"ok": true, "value": "repaired"}',
            ]
        )
        client = LLMClient(
            self._settings(),
            models=["fake"],
            chat_factory=lambda model: _FakeChat(next(responses)),
        )
        result, _ = client.generate_json("sys", "user", _SimpleModel)
        self.assertEqual(result.value, "repaired")

    def test_fallback_to_next_model(self) -> None:
        def factory(model: str):
            if model == "bad":
                return _FakeChat(RuntimeError("429 rate limit"))
            return _FakeChat('{"ok": true, "value": "fallback"}')

        client = LLMClient(
            self._settings(),
            models=["bad", "good"],
            chat_factory=factory,
        )
        result, model = client.generate_json("sys", "user", _SimpleModel)
        self.assertEqual(model, "good")
        self.assertEqual(result.value, "fallback")

    def test_all_models_fail(self) -> None:
        client = LLMClient(
            self._settings(),
            models=["bad"],
            chat_factory=lambda model: _FakeChat(RuntimeError("boom")),
        )
        with self.assertRaises(LLMError):
            client.generate_json("sys", "user", _SimpleModel)


if __name__ == "__main__":
    unittest.main()
