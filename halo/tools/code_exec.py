import logging
import sys
from io import StringIO
from typing import Any, ClassVar

from halo.tools.base import BaseTool

log = logging.getLogger("halo.tools.code")


class PythonExecTool(BaseTool):
    name: ClassVar[str] = "code_python"
    description: ClassVar[str] = "Execute Python code in an isolated sandbox. Returns stdout, stderr, and any exception."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute",
            },
        },
        "required": ["code"],
    }

    def execute(self, code: str, **kwargs: Any) -> Any:
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        result: dict = {"stdout": "", "stderr": "", "error": None}

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            compiled = compile(code, "<halo_code>", "exec", flags=0)
            namespace: dict = {}
            exec(compiled, namespace)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()

        return result
