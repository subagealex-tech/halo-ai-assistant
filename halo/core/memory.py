import logging
from collections import deque

log = logging.getLogger("halo.memory")


class ConversationMemory:
    def __init__(self, max_messages: int = 100) -> None:
        self._messages: deque[dict] = deque(maxlen=max_messages)
        self._system_prompt: str | None = None

    def set_system(self, prompt: str) -> None:
        self._system_prompt = prompt

    def add(self, message: dict) -> None:
        self._messages.append(message)

    def add_user(self, content: str) -> None:
        self.add({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.add({"role": "assistant", "content": content})

    def add_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.add({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    def build_context(self) -> list[dict]:
        if self._system_prompt:
            return [{"role": "system", "content": self._system_prompt}, *list(self._messages)]
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    @property
    def history(self) -> list[dict]:
        return list(self._messages)
