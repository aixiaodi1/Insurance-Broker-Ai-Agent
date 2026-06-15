import os
from pathlib import Path

from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    data_dir: Path = Path("data")
    local_source_root: Path = PROJECT_ROOT
    memory_db_path: Path = Path("data/memory/agent_memory.sqlite3")
    hermes_memory_dir: Path = PROJECT_ROOT
    hermes_memory_char_limit: int = 2200
    hermes_user_char_limit: int = 1375
    runs_dir: Path = Path("data/runs")
    source_registry_path: Path = Path("data/source_registry/insurance_products.json")
    enable_web_search: bool = os.getenv("AGENT_ENABLE_WEB_SEARCH", "1") not in {"0", "false", "False"}
    max_messages_before_summary: int = 20
    max_tool_events_before_summary: int = 50
    compact_max_messages: int = 12
    compact_max_tool_events: int = 20
    compact_input_max_chars: int = 20000
    compact_enabled: bool = True
    compact_max_consecutive_failures: int = 3
    llm_api_base_url: str = os.getenv("LLM_API_BASE_URL", "")
    llm_api_path: str = os.getenv("LLM_API_PATH", "/chat/completions")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    minimax_api_key: str = os.getenv("MINIMAX_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "llm")
    subagent_contracts_dir: str = os.getenv("SUBAGENT_CONTRACTS_DIR", "")


settings = Settings()
