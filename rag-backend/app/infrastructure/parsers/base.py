from pathlib import Path
from typing import Protocol


class DocumentParser(Protocol):
    def parse(self, path: Path) -> str: ...
