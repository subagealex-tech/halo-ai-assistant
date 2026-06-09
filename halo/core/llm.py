import logging
from typing import Any

from openai import OpenAI, AsyncOpenAI

log = logging.getLogger("halo.llm")


class LLMClient:
    def __init__(self, config: "HALOConfig") -> None:
        self.config = config
        api_key = config.llm_api_key or "sk-placeholder"
        kwargs: dict[str, Any] = {"api_key": api_key}
        if config.llm_base_url:
            kwargs["base_url"] = config.llm_base_url
        self._client = OpenAI(**kwargs)
        self._async_client = AsyncOpenAI(**kwargs)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        kwargs = dict(
            model=self.config.llm_model,
            messages=messages,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        return self._parse(resp)

    async def chat_async(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        kwargs = dict(
            model=self.config.llm_model,
            messages=messages,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = await self._async_client.chat.completions.create(**kwargs)
        return self._parse(resp)

    def _parse(self, resp: Any) -> dict:
        choice = resp.choices[0]
        msg = choice.message
        result: dict = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [],
        }
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        return result
