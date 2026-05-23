from pathlib import Path


class PdfParser:
    def parse(self, path: Path) -> str:
        from pypdf import PdfReader

        reader = PdfReader(path)
        page_text = [text for page in reader.pages if (text := page.extract_text())]
        return "\n".join(page_text)
