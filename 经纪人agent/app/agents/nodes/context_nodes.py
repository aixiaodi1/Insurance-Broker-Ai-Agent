from typing import Any

import app.agents.compact.compactor as _compactor


def compact_context(state: dict[str, Any], llm_client: Any = None) -> dict[str, Any]:
    return _compactor.compact_context(state, llm_client=llm_client)
