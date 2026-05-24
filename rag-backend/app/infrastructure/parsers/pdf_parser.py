from pathlib import Path

from app.errors import NonRetryableIngestionError


class PdfParser:
    def parse(self, path: Path) -> str:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError, PdfStreamError

        try:
            reader = PdfReader(path)
            page_text = [text for page in reader.pages if (text := page.extract_text())]
            return "\n".join(page_text)
        except (PdfReadError, PdfStreamError, EOFError) as exc:
            raise NonRetryableIngestionError("PDF parsing failed.") from exc
