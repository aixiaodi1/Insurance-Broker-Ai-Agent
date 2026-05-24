from typing import Protocol

from app.domain import TextChunk


class Chunker(Protocol):
    def split(self, text: str) -> list[TextChunk]: ...
