from pathlib import Path


class TextParser:
    def parse(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")
