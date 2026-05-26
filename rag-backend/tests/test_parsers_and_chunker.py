from pathlib import Path

import pytest

from app.errors import NonRetryableIngestionError
from app.infrastructure.chunkers.document_aware import DocumentAwareChunker
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


def test_document_aware_chunker_splits_insurance_clauses_by_clause_heading() -> None:
    text = (
        "XX\u91cd\u75be\u9669\u4fdd\u9669\u6761\u6b3e\n"
        "\u7b2c\u4e00\u6761 \u4fdd\u9669\u5408\u540c\u6784\u6210\n"
        "\u672c\u4fdd\u9669\u5408\u540c\u7531\u4fdd\u9669\u5355\u3001\u6295\u4fdd\u5355\u3001\u4fdd\u9669\u6761\u6b3e\u7ec4\u6210\u3002\n"
        "\u7b2c\u4e8c\u6761 \u4fdd\u9669\u8d23\u4efb\n"
        "\u88ab\u4fdd\u9669\u4eba\u5728\u7b49\u5f85\u671f\u540e\u786e\u8bca\u91cd\u5927\u75be\u75c5\u7684\uff0c"
        "\u672c\u516c\u53f8\u6309\u7ea6\u5b9a\u7ed9\u4ed8\u91cd\u5927\u75be\u75c5\u4fdd\u9669\u91d1\u3002\n"
        "\u7b2c\u4e09\u6761 \u8d23\u4efb\u514d\u9664\n"
        "\u56e0\u6295\u4fdd\u4eba\u6545\u610f\u9020\u6210\u88ab\u4fdd\u9669\u4eba\u8eab\u6545\u3001"
        "\u4f24\u6b8b\u6216\u75be\u75c5\u7684\uff0c\u672c\u516c\u53f8\u4e0d\u627f\u62c5\u4fdd\u9669\u8d23\u4efb\u3002"
    )

    chunks = DocumentAwareChunker(chunk_size=120, chunk_overlap=20).split(text)

    assert len(chunks) == 3
    assert chunks[0].metadata["document_type"] == "insurance_clause"
    assert chunks[1].metadata["clause_title"] == "\u7b2c\u4e8c\u6761 \u4fdd\u9669\u8d23\u4efb"
    assert chunks[1].metadata["chunk_strategy"] == "insurance_clause"
    assert "\u91cd\u5927\u75be\u75c5\u4fdd\u9669\u91d1" in chunks[1].text


def test_document_aware_chunker_splits_claim_cases_by_case_heading() -> None:
    text = (
        "5\u4e2a\u62d2\u8d54\u6848\u4f8b\u76f4\u64ad\u7a3f\n"
        "\u6848\u4f8b\u4e00\uff1a\u672a\u5982\u5b9e\u5065\u5eb7\u544a\u77e5\u5bfc\u81f4\u62d2\u8d54\n"
        "\u5ba2\u6237\u6295\u4fdd\u524d\u5df2\u6709\u7532\u72b6\u817a\u7ed3\u8282\uff0c"
        "\u4f46\u5065\u5eb7\u544a\u77e5\u4e2d\u6ca1\u6709\u8bf4\u660e\u3002"
        "\u62d2\u8d54\u539f\u56e0\u662f\u672a\u5982\u5b9e\u544a\u77e5\u3002\n"
        "\u7ed3\u8bba\uff1a\u6295\u4fdd\u524d\u8981\u8ba4\u771f\u6838\u5bf9\u5065\u5eb7\u544a\u77e5\u3002\n"
        "\u6848\u4f8b\u4e8c\uff1a\u7b49\u5f85\u671f\u5185\u51fa\u9669\n"
        "\u5ba2\u6237\u6295\u4fdd\u540e\u7b2c20\u5929\u786e\u8bca\uff0c\u4ecd\u5728\u7b49\u5f85\u671f\u5185\u3002"
        "\u4fdd\u9669\u516c\u53f8\u6309\u7167\u6761\u6b3e\u4e0d\u627f\u62c5\u4fdd\u9669\u91d1\u8d23\u4efb\u3002\n"
        "\u7ed3\u8bba\uff1a\u7b49\u5f85\u671f\u662f\u7406\u8d54\u5224\u65ad\u7684\u5173\u952e\u6761\u4ef6\u3002"
    )

    chunks = DocumentAwareChunker(chunk_size=120, chunk_overlap=20).split(text)

    assert len(chunks) == 2
    assert chunks[0].metadata["document_type"] == "claim_case"
    assert chunks[0].metadata["chunk_type"] == "case"
    assert chunks[1].metadata["section_title"] == "\u6848\u4f8b\u4e8c\uff1a\u7b49\u5f85\u671f\u5185\u51fa\u9669"


def test_document_aware_chunker_falls_back_to_chinese_character_chunks() -> None:
    text = "\u8fd9\u662f\u4e00\u6bb5\u6ca1\u6709\u7a7a\u683c\u7684\u4e2d\u6587\u76f4\u64ad\u7a3f\u5185\u5bb9\u3002" * 120

    chunks = DocumentAwareChunker(chunk_size=180, chunk_overlap=30).split(text)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 180 for chunk in chunks)
    assert chunks[0].metadata["document_type"] == "live_script"
    assert chunks[0].metadata["chunk_strategy"] == "char_cn"
