from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.memory.llm import HTTPChatMemoryExtractor, build_memory_extractor_from_settings
from app.subagent.loader import SubagentLoader
from app.subagent.runner import SubagentRunner


def build_subagent_runner() -> SubagentRunner | None:
    llm_client = build_memory_extractor_from_settings(settings)
    if llm_client is None:
        return None

    contracts_dir = getattr(settings, "subagent_contracts_dir", "")
    if not contracts_dir:
        contracts_dir = Path(__file__).resolve().parent / "contracts"

    loader = SubagentLoader(
        contracts_dir=contracts_dir,
        ttl_seconds=60,
    )
    return SubagentRunner(
        loader=loader,
        llm_client=llm_client,
        contracts_dir=contracts_dir,
    )
