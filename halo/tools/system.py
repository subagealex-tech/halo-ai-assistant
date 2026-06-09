import logging
import shlex
import subprocess
from typing import Any, ClassVar

from halo.tools.base import BaseTool

log = logging.getLogger("halo.tools.system")


class SystemExecTool(BaseTool):
    name: ClassVar[str] = "system_exec"
    description: ClassVar[str] = "Execute a system command and return stdout/stderr. Use with caution."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    def execute(self, command: str, timeout: int = 30, **kwargs: Any) -> Any:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"error": str(e)}
