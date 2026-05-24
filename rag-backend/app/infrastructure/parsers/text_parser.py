from pathlib import Path

from app.errors import NonRetryableIngestionError


class TextParser:
    def parse(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise NonRetryableIngestionError("Document decoding failed.") from exc
