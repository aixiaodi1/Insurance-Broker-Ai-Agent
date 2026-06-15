from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ContextEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def should_compress(self, state: dict[str, Any]) -> bool:
        ...

    @abstractmethod
    def compress(
        self, state: dict[str, Any], llm_client: Any = None
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def update_from_response(self, usage: dict[str, Any]) -> None:
        ...

    def on_session_reset(self) -> None:
        ...
