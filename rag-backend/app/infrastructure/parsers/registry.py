from pathlib import Path

from app.infrastructure.parsers.base import DocumentParser
from app.infrastructure.parsers.markdown_parser import MarkdownParser
from app.infrastructure.parsers.pdf_parser_v2 import PdfParserV2
from app.infrastructure.parsers.text_parser import TextParser


class ParserRegistry:
    def __init__(self, parsers: dict[str, DocumentParser]) -> None:
        self._parsers = parsers

    @classmethod
    def default(cls) -> "ParserRegistry":
        return cls(
            {
                ".txt": TextParser(),
                ".md": MarkdownParser(),
                ".pdf": PdfParserV2(),
            }
        )

    def parse(self, path: Path) -> str:
        suffix = path.suffix.lower()
        parser = self._parsers.get(suffix)
        if parser is None:
            raise ValueError(f"Unsupported file extension: {suffix}")

        return parser.parse(path)
