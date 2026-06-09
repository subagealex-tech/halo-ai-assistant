import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HALOConfig:
    llm_provider: str = os.getenv("HALO_LLM_PROVIDER", "openai")
    llm_model: str = os.getenv("HALO_LLM_MODEL", "gpt-4o")
    llm_api_key: str = os.getenv("HALO_API_KEY", "")
    llm_base_url: str = os.getenv("HALO_BASE_URL", "")
    llm_temperature: float = float(os.getenv("HALO_TEMPERATURE", "0.3"))
    llm_max_tokens: int = int(os.getenv("HALO_MAX_TOKENS", "4096"))

    system_prompt: str = os.getenv(
        "HALO_SYSTEM_PROMPT",
        "You are H.A.L.O. (Heuristic Automated Logic Operator). "
        "You are an elite AI assistant — polished, precise, and quietly confident. "
        "Speak like a digital co-pilot, not a chatbot. Be concise. Use wit when appropriate. "
        "Address the user as 'Boss'.",
    )

    memory_max_messages: int = int(os.getenv("HALO_MEMORY_MAX", "100"))
    memory_db_path: Path = Path(
        os.getenv("HALO_MEMORY_PATH", str(Path.home() / ".halo" / "memory.db"))
    )

    workspace_root: Path = Path(os.getenv("HALO_WORKSPACE", Path.cwd()))

    web_search_enabled: bool = os.getenv("HALO_WEB_SEARCH", "true").lower() == "true"
    code_exec_enabled: bool = os.getenv("HALO_CODE_EXEC", "false").lower() == "true"

    log_level: str = os.getenv("HALO_LOG_LEVEL", "INFO")

    tools_enabled: list[str] = field(default_factory=lambda: [
        "web_search", "web_fetch", "file_read", "file_write",
        "file_list", "system_exec", "code_python",
    ])

    @classmethod
    def load(cls) -> "HALOConfig":
        return cls()
