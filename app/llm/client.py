"""LLM 客户端：智谱 OpenAI 兼容接口 + JSON 校验 + 模型降级。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_UNWRAP_KEYS = ("markdown", "answer", "content", "output", "result", "data")


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        models: list[str] | None = None,
        chat_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.models = list(
            dict.fromkeys(
                models
                or [
                    settings.llm_model,
                    settings.llm_fallback_model,
                    "glm-4-flash",
                ]
            )
        )
        self._chat_factory = chat_factory or self._default_chat_factory

    @property
    def available(self) -> bool:
        return self.settings.llm_configured()

    def _default_chat_factory(self, model: str) -> ChatOpenAI:
        if not self.settings.llm_configured():
            raise LLMError("未配置 LLM_API_KEY")
        return ChatOpenAI(
            model=model,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key.get_secret_value(),
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            timeout=self.settings.llm_timeout,
            max_retries=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> tuple[T, str]:
        """返回 (校验后的对象, 实际使用的模型)。"""
        last_error: Exception | None = None
        for model in self.models:
            for attempt in range(2):
                prompt = user_prompt
                if attempt == 1:
                    prompt = (
                        user_prompt
                        + "\n\n上一次输出无法解析或不符合 schema："
                        + str(last_error)[:300]
                        + "\n请只输出一个合法 JSON 对象，不要 markdown、不要解释。"
                    )
                try:
                    chat = self._chat_factory(model)
                    if max_tokens is not None:
                        chat = chat.bind(max_tokens=max_tokens)
                    response = chat.invoke(
                        [
                            SystemMessage(content=system_prompt),
                            HumanMessage(content=prompt),
                        ]
                    )
                    text = _content_to_text(response.content)
                    data = _unwrap_json(parse_json_object(text))
                    parsed = schema.model_validate(data)
                    return parsed, model
                except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                    last_error = exc
                    logger.warning("LLM JSON 解析失败 model=%s: %s", model, exc)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning("LLM 调用失败 model=%s: %s", model, exc)
                    break
        raise LLMError(f"所有 LLM 模型均失败: {last_error}") from last_error


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = _CODE_FENCE.sub("", text.strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出中没有 JSON 对象")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 根节点不是对象")
    return data


def _unwrap_json(data: dict[str, Any]) -> dict[str, Any]:
    for key in _UNWRAP_KEYS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, dict):
            return _unwrap_json(value)
        if isinstance(value, str):
            try:
                nested = parse_json_object(value)
                return _unwrap_json(nested)
            except (ValueError, json.JSONDecodeError):
                continue
    return data
