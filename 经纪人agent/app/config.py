import os
from pathlib import Path

from pydantic import BaseModel
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_env(project_root: Path = PROJECT_ROOT) -> None:
    load_dotenv(project_root / ".env", override=False, encoding="utf-8")


load_project_env()


class Settings(BaseModel):
    data_dir: Path = Path("data")
    local_source_root: Path = PROJECT_ROOT
    memory_db_path: Path = Path("data/memory/agent_memory.sqlite3")
    web_acquisition_db_path: Path = Path("data/web_acquisition/acquisition.sqlite3")
    hermes_memory_dir: Path = PROJECT_ROOT
    hermes_memory_char_limit: int = 2200
    hermes_user_char_limit: int = 1375
    runs_dir: Path = Path("data/runs")
    source_registry_path: Path = Path("data/source_registry/insurance_products.json")
    enable_web_search: bool = os.getenv("AGENT_ENABLE_WEB_SEARCH", "1") not in {"0", "false", "False"}
    search_primary_provider: str = os.getenv("SEARCH_PRIMARY_PROVIDER", "baidu_qianfan")
    search_fallback_provider: str = os.getenv("SEARCH_FALLBACK_PROVIDER", "firecrawl")
    search_high_risk_dual_provider: bool = os.getenv("SEARCH_HIGH_RISK_DUAL_PROVIDER", "1") not in {"0", "false", "False"}
    search_timeout_seconds: int = int(os.getenv("SEARCH_TIMEOUT_SECONDS", "8"))
    search_max_results: int = int(os.getenv("SEARCH_MAX_RESULTS", "8"))
    search_enable_fallback: bool = os.getenv("SEARCH_ENABLE_FALLBACK", "1") not in {"0", "false", "False"}
    baidu_qianfan_api_key: str = os.getenv("BAIDU_QIANFAN_API_KEY", "")
    baidu_qianfan_search_endpoint: str = os.getenv("BAIDU_QIANFAN_SEARCH_ENDPOINT", "https://qianfan.baidubce.com/v2/ai_search/web_search")
    firecrawl_api_key: str = os.getenv("FIRECRAWL_API_KEY", "")
    firecrawl_search_endpoint: str = os.getenv("FIRECRAWL_SEARCH_ENDPOINT", "https://api.firecrawl.dev/v2/search")
    firecrawl_scrape_endpoint: str = os.getenv("FIRECRAWL_SCRAPE_ENDPOINT", "https://api.firecrawl.dev/v2/scrape")
    search_trusted_domains: str = os.getenv("SEARCH_TRUSTED_DOMAINS", "")
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
