import logging
from pathlib import Path
from typing import Any, ClassVar

from halo.tools.base import BaseTool

log = logging.getLogger("halo.tools.file_ops")


class FileReadTool(BaseTool):
    name: ClassVar[str] = "file_read"
    description: ClassVar[str] = "Read the contents of a file. Returns the text content."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file",
            },
        },
        "required": ["path"],
    }

    def execute(self, path: str, **kwargs: Any) -> Any:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"error": f"File not found: {p}"}
        if not p.is_file():
            return {"error": f"Not a file: {p}"}
        try:
            content = p.read_text(encoding="utf-8")
            return {"path": str(p), "content": content, "size": len(content)}
        except Exception as e:
            return {"error": str(e)}


class FileWriteTool(BaseTool):
    name: ClassVar[str] = "file_write"
    description: ClassVar[str] = "Write content to a file. Creates parent directories if needed."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file",
            },
            "content": {
                "type": "string",
                "description": "Text content to write",
            },
        },
        "required": ["path", "content"],
    }

    def execute(self, path: str, content: str, **kwargs: Any) -> Any:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(content, encoding="utf-8")
            return {"path": str(p), "written": len(content), "status": "ok"}
        except Exception as e:
            return {"error": str(e)}


class FileListTool(BaseTool):
    name: ClassVar[str] = "file_list"
    description: ClassVar[str] = "List files and directories at a given path."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list",
                "default": ".",
            },
            "pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter (e.g. '*.py')",
                "default": "",
            },
        },
        "required": [],
    }

    def execute(self, path: str = ".", pattern: str = "", **kwargs: Any) -> Any:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"error": f"Path not found: {p}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {p}"}
        try:
            if pattern:
                entries = list(p.glob(pattern))
            else:
                entries = list(p.iterdir())
            files = []
            for e in sorted(entries):
                files.append({
                    "name": e.name,
                    "type": "dir" if e.is_dir() else "file",
                    "size": e.stat().st_size if e.is_file() else 0,
                })
            return {"path": str(p), "entries": files, "count": len(files)}
        except Exception as e:
            return {"error": str(e)}
