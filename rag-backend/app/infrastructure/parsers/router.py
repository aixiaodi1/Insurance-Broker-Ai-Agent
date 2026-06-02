from pathlib import Path

from app.domain import ParseReport
from app.infrastructure.parsers.base import DocumentParser
from app.infrastructure.parsers.quality_gate import ParseQualityGate


class ParserRouter:
    """Routes documents to the best parser based on file type and parse quality.

    PR-0: Design with extension-based routing + quality gate integration.
    PR-1+: Add per-parse quality comparison across PyMuPDF/pypdf candidates.
    """

    def __init__(
        self,
        parsers: dict[str, DocumentParser],
        quality_gate: ParseQualityGate | None = None,
    ) -> None:
        self._parsers = parsers
        self._quality_gate = quality_gate

    def select_parser(self, path: Path) -> DocumentParser:
        suffix = path.suffix.lower()
        parser = self._parsers.get(suffix)
        if parser is None:
            raise ValueError(f"Unsupported file extension: {suffix}")
        return parser

    def parse(self, path: Path) -> str:
        parser = self.select_parser(path)
        return parser.parse(path)

    def parse_with_report(self, path: Path) -> tuple[str, ParseReport | None]:
        parser = self.select_parser(path)
        parse_with_report = getattr(parser, "parse_with_report", None)
        if parse_with_report is not None:
            return parse_with_report(path)
        text = parser.parse(path)
        return text, None

    @classmethod
    def default(cls) -> "ParserRouter":
        from app.infrastructure.parsers.markdown_parser import MarkdownParser
        from app.infrastructure.parsers.pdf_parser_v2 import PdfParserV2
        from app.infrastructure.parsers.text_parser import TextParser

        return cls(
            parsers={
                ".txt": TextParser(),
                ".md": MarkdownParser(),
                ".pdf": PdfParserV2(),
            },
            quality_gate=ParseQualityGate(),
        )
