import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

log = logging.getLogger("halo.tools")


class BaseTool(ABC):
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, config: Any = None) -> None:
        self.config = config

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any: ...

    def to_openai_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, config: "HALOConfig") -> None:
        self.config = config
        self._tools: dict[str, BaseTool] = {}
        self._discover()

    def _discover(self) -> None:
        from halo.tools.web import WebSearchTool, WebFetchTool
        from halo.tools.file_ops import FileReadTool, FileWriteTool, FileListTool
        from halo.tools.system import SystemExecTool
        from halo.tools.code_exec import PythonExecTool

        for cls in [
            WebSearchTool,
            WebFetchTool,
            FileReadTool,
            FileWriteTool,
            FileListTool,
            SystemExecTool,
            PythonExecTool,
        ]:
            instance = cls(config=self.config)
            self._tools[instance.name] = instance

    @property
    def tools(self) -> dict[str, BaseTool]:
        return self._tools

    def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        try:
            return tool.execute(**kwargs)
        except Exception as e:
            log.exception("Tool %s failed", name)
            return {"error": str(e)}
