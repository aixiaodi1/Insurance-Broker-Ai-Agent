from pathlib import Path
from typing import Protocol

from app.domain import ParseReport


class DocumentParser(Protocol):
    def parse(self, path: Path) -> str: ...

    def parse_with_report(self, path: Path) -> tuple[str, ParseReport | None]:
        text = self.parse(path)
        return text, None
