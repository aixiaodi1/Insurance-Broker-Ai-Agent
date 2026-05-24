from pathlib import Path

import pytest

from app.errors import NonRetryableIngestionError
from app.infrastructure.chunkers.recursive import RecursiveTextChunker
from app.infrastructure.parsers.pdf_parser import PdfParser
from app.infrastructure.parsers.registry import ParserRegistry
from app.infrastructure.parsers.text_parser import TextParser


def test_text_and_markdown_parsers_extract_text(tmp_path: Path) -> None:
    txt = tmp_path / "note.txt"
    md = tmp_path / "note.md"
    txt.write_text("plain text", encoding="utf-8")
    md.write_text("# Title\n\nmarkdown text", encoding="utf-8")

    registry = ParserRegistry.default()

    assert registry.parse(txt) == "plain text"
    assert "markdown text" in registry.parse(md)


def test_registry_rejects_unsupported_extension(tmp_path: Path) -> None:
    file_path = tmp_path / "table.xlsx"
    file_path.write_text("not supported", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file extension"):
        ParserRegistry.default().parse(file_path)


def test_text_parser_wraps_decode_errors_as_nonretryable(tmp_path: Path) -> None:
    file_path = tmp_path / "bad.txt"
    file_path.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(NonRetryableIngestionError, match="Document decoding failed"):
        TextParser().parse(file_path)


def test_pdf_parser_wraps_invalid_pdf_as_nonretryable(tmp_path: Path) -> None:
    file_path = tmp_path / "bad.pdf"
    file_path.write_bytes(b"not a pdf")

    with pytest.raises(NonRetryableIngestionError, match="PDF parsing failed"):
        PdfParser().parse(file_path)


def test_recursive_chunker_defaults_to_500_with_50_overlap() -> None:
    text = " ".join(str(index) for index in range(650))
    chunker = RecursiveTextChunker()
    chunks = chunker.split(text)

    assert chunker.chunk_size == 500
    assert chunker.chunk_overlap == 50
    assert chunks[0].chunk_index == 0
    assert len(chunks) >= 2
    assert chunks[0].token_count <= 500


def test_recursive_chunker_reuses_overlap_tokens() -> None:
    text = " ".join(str(index) for index in range(12))
    chunker = RecursiveTextChunker(chunk_size=5, chunk_overlap=2)

    chunks = chunker.split(text)

    assert chunks[0].text == "0 1 2 3 4"
    assert chunks[1].text.startswith("3 4")
    assert chunks[1].chunk_index == 1


def test_recursive_chunker_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="Cannot chunk empty text"):
        RecursiveTextChunker().split(" \n\t ")


def test_recursive_chunker_rejects_overlap_at_least_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
        RecursiveTextChunker(chunk_size=50, chunk_overlap=50)
