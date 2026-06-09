import json
import logging
from typing import Any

from config import HALOConfig
from halo.core.llm import LLMClient
from halo.core.memory import ConversationMemory
from halo.tools.base import ToolRegistry

log = logging.getLogger("halo.engine")


class HALOEngine:
    def __init__(self, config: HALOConfig) -> None:
        self.config = config
        self.llm = LLMClient(config)
        self.memory = ConversationMemory(max_messages=config.memory_max_messages)
        self.memory.set_system(config.system_prompt)
        self.registry = ToolRegistry(config)

    def _build_tool_defs(self) -> list[dict]:
        return [
            tool.to_openai_spec()
            for name, tool in self.registry.tools.items()
            if name in self.config.tools_enabled
        ]

    def process_message(self, user_input: str, stream_handler: Any = None) -> str:
        self.memory.add_user(user_input)

        for _ in range(10):
            message = self.llm.chat(
                messages=self.memory.build_context(),
                tools=self._build_tool_defs(),
            )

            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            if content and stream_handler:
                stream_handler(content)

            if not tool_calls:
                if content:
                    self.memory.add_assistant(content)
                return content or "[No response generated]"

            self.memory.add({
                "role": "assistant",
                "content": content or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                log.info("Tool call: %s(%s)", fn_name, fn_args)

                result = self.registry.execute(fn_name, **fn_args)

                if stream_handler:
                    stream_handler(f"\n  ⚡ [{fn_name}] → done\n")

                self.memory.add_tool_result(
                    tool_call_id=tc["id"],
                    name=fn_name,
                    content=json.dumps(result, default=str),
                )

        return "[Max tool call depth reached]"
