from pathlib import Path

import pytest

from app.errors import NonRetryableIngestionError
from app.infrastructure.chunkers.document_aware import DocumentAwareChunker
from app.infrastructure.chunkers.recursive import RecursiveTextChunker
from app.infrastructure.parsers.pdf_parser_v2 import PdfParserV2
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


def test_pdf_parser_v2_wraps_invalid_pdf_as_nonretryable(tmp_path: Path) -> None:
    file_path = tmp_path / "bad.pdf"
    file_path.write_bytes(b"not a pdf")

    with pytest.raises(NonRetryableIngestionError, match="Failed to open PDF"):
        PdfParserV2().parse(file_path)


def test_pdf_parser_v2_produces_sidecar_files(tmp_path: Path) -> None:
    import fitz
    file_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "2.4.1 Major Disease Insurance Benefit", fontsize=12)
    page.insert_text((72, 100), "The insured person diagnosed with major disease after waiting period.", fontsize=12)
    page.insert_text((72, 130), "Article 1 Insurance Contract Composition", fontsize=12)
    page.insert_text((72, 160), "This contract consists of insurance policy and terms.", fontsize=12)
    doc.save(str(file_path))
    doc.close()

    parser = PdfParserV2()
    text = parser.parse(file_path)

    assert "Major Disease Insurance Benefit" in text
    assert "Article 1" in text
    assert (tmp_path / "raw_lines.json").exists()
    assert (tmp_path / "parsed_clean.md").exists()
    assert (tmp_path / "parse_report.json").exists()


def test_pdf_parser_v2_parse_with_report_returns_report(tmp_path: Path) -> None:
    import fitz
    file_path = tmp_path / "report_sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Insurance clause test content", fontsize=12)
    doc.save(str(file_path))
    doc.close()

    text, report = PdfParserV2().parse_with_report(file_path)

    assert text.strip() == "Insurance clause test content"
    assert report is not None
    assert report.quality_score > 0
    assert report.total_pages == 1


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
    assert chunks[1].metadata["content_type"] == "insurance_liability"
    assert chunks[2].metadata["content_type"] == "exclusion"
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


def test_pdf_parser_v2_fixes_broken_chinese_words() -> None:
    parser = PdfParserV2()
    fixed, count = parser._fix_broken_words("\u91cd \u75c7 \u4fdd\u9669")
    assert count == 1
    assert "\u91cd\u75c7\u4fdd\u9669" in fixed


def test_pdf_parser_v2_detects_clause_titles() -> None:
    assert PdfParserV2()._count_clause_titles(["2.4.1 \u91cd\u5ea6\u75be\u75c5\u4fdd\u9669\u91d1", "some text", "10.2.3 \u8d23\u4efb\u514d\u9664"]) == 2


def test_pdf_parser_v2_detects_page_numbers() -> None:
    parser = PdfParserV2()
    assert parser._is_page_number("1") is True
    assert parser._is_page_number("- 5 -") is True
    assert parser._is_page_number("\u2014 12 \u2014") is True
    assert parser._is_page_number("\u7b2c\u4e00\u9875") is True
    assert parser._is_page_number("2.4.1 insurance") is False


def test_pdf_parser_v2_detects_table_lines() -> None:
    parser = PdfParserV2()
    assert parser._is_table_line("TNM \u5206\u671f I", "TNM \u5206\u671f I") is True
    assert parser._is_table_line("5x10x20", "5x10x20") is True
    assert parser._is_table_line("normal text paragraph", "normal text paragraph") is False


def test_pdf_parser_v2_sentence_end_detection() -> None:
    parser = PdfParserV2()
    cleaned: list[str] = []
    assert parser._is_sentence_end("\u91cd\u75c7\u4fdd\u9669\u91d1\u3002", cleaned) is True
    assert parser._is_sentence_end("\u91cd\u75c7\u4fdd\u9669\u91d1", cleaned) is False
    assert parser._is_sentence_end("2.4.1 \u91cd\u5ea6\u75be\u75c5", cleaned) is True


def test_pdf_parser_v2_quality_gate_rejects_empty_pdf(tmp_path: Path) -> None:
    import fitz
    file_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(file_path))
    doc.close()

    parser = PdfParserV2()
    text, report = parser.parse_with_report(file_path)

    assert text == ""
    assert report.total_pages == 1
    assert report.total_lines == 0


def test_parse_quality_gate(tmp_path: Path) -> None:
    from app.infrastructure.parsers.quality_gate import ParseQualityGate
    from app.domain import ParseReport, ParseStatus, ParserType, QualityWarning

    gate = ParseQualityGate()
    good_report = ParseReport(
        parser_name="test", parse_status=ParseStatus.SUCCESS,
        quality_score=0.8, total_pages=1, total_lines=50,
        selected_parser=ParserType.PYMUPDF,
    )
    assert gate.evaluate(good_report) is True

    bad_report = ParseReport(
        parser_name="test", parse_status=ParseStatus.SUCCESS,
        quality_score=0.1, total_pages=1, total_lines=2,
        selected_parser=ParserType.PYMUPDF,
        warnings=[QualityWarning.OCR_NEEDED],
        needs_ocr=True,
    )
    assert gate.evaluate(bad_report) is False

    ocr_report = ParseReport(
        parser_name="test", parse_status=ParseStatus.SUCCESS,
        quality_score=0.6, total_pages=1, total_lines=50,
        selected_parser=ParserType.PYMUPDF,
        warnings=[QualityWarning.OCR_NEEDED],
        needs_ocr=True,
    )
    assert gate.evaluate(ocr_report) is False
    assert "ocr_needed" in gate.needs_manual_review(ocr_report)


def test_parser_router_routes_pdf_to_v2(tmp_path: Path) -> None:
    from app.infrastructure.parsers.router import ParserRouter
    import fitz

    router = ParserRouter.default()
    file_path = tmp_path / "router_test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Router test content", fontsize=12)
    doc.save(str(file_path))
    doc.close()

    text = router.parse(file_path)
    assert "Router test content" in text

    text2, report = router.parse_with_report(file_path)
    assert "Router test content" in text2
    assert report is not None


def test_document_aware_chunker_splits_numbered_clauses() -> None:
    text = (
        "\u4fdd\u9669\u6761\u6b3e\n"
        "2.4.1 \u91cd\u5ea6\u75be\u75c5\u4fdd\u9669\u91d1\n"
        "\u88ab\u4fdd\u9669\u4eba\u5728\u7b49\u5f85\u671f\u540e\u786e\u8bca\u7684\uff0c\u6309\u7ea6\u5b9a\u7ed9\u4ed8\u3002\n"
        "2.6 \u8d23\u4efb\u514d\u9664\n"
        "\u56e0\u6545\u610f\u884c\u4e3a\u5bfc\u81f4\u7684\uff0c\u4e0d\u627f\u62c5\u4fdd\u9669\u8d23\u4efb\u3002"
    )

    chunks = DocumentAwareChunker(chunk_size=200, chunk_overlap=20).split(text)

    assert len(chunks) == 2
    assert chunks[0].metadata["section_no"] == "2.4.1"
    assert "\u91cd\u5ea6\u75be\u75c5\u4fdd\u9669\u91d1" in chunks[0].metadata["section_title"]
    assert chunks[0].metadata["content_type"] == "insurance_liability"
    assert chunks[1].metadata["section_no"] == "2.6"
    assert chunks[1].metadata["content_type"] == "exclusion"


def test_document_aware_chunker_classifies_exclusion_content_type() -> None:
    text = (
        "\u4fdd\u9669\u6761\u6b3e\u6d4b\u8bd5\n"
        "10.2 \u8d23\u4efb\u514d\u9664\n"
        "\u56e0\u4ee5\u4e0b\u539f\u56e0\u5bfc\u81f4\u7684\uff0c\u4fdd\u9669\u4eba\u4e0d\u627f\u62c5\u8d54\u507f\u8d23\u4efb\uff1a\n"
        "\uff08\u4e00\uff09\u6295\u4fdd\u4eba\u7684\u6545\u610f\u884c\u4e3a\uff1b\n"
        "\uff08\u4e8c\uff09\u88ab\u4fdd\u9669\u4eba\u81ea\u827a\u4f24\u5bb3\u6216\u81ea\u6740\u3002\n"
        "13.22 TNM \u5206\u671f\n"
        "Stage I\uff1a\u80bf\u7624\u5c40\u9650\u4e8e\u539f\u53d1\u90e8\u4f4d\n"
        "Stage II\uff1a\u6709\u533a\u57df\u6dcb\u5df4\u7ed3\u8f6c\u79fb"
    )

    chunks = DocumentAwareChunker(chunk_size=300, chunk_overlap=30).split(text)

    exclusion_chunks = [c for c in chunks if c.metadata.get("content_type") == "exclusion"]
    table_chunks = [c for c in chunks if c.metadata.get("content_type") == "table_candidate"]

    assert len(exclusion_chunks) >= 1
    assert exclusion_chunks[0].metadata["section_no"] == "10.2"
    assert len(table_chunks) >= 1
    assert table_chunks[0].metadata["section_no"] == "13.22"


def test_document_aware_chunker_detects_table_candidates() -> None:
    text = (
        "\u4fdd\u9669\u6761\u6b3e\n"
        "13.22 TNM \u5206\u671f\n"
        "Stage I | \u80bf\u7624\u5c40\u9650\u4e8e\u539f\u53d1\u90e8\u4f4d | 5\u5e74\u751f\u5b58\u7387 90%\n"
        "Stage II | \u6709\u533a\u57df\u6dcb\u5df4\u7ed3\u8f6c\u79fb | 5\u5e74\u751f\u5b58\u7387 70%\n"
        "Stage III | \u8fdc\u5904\u8f6c\u79fb | 5\u5e74\u751f\u5b58\u7387 30%"
    )

    chunks = DocumentAwareChunker(chunk_size=300, chunk_overlap=30).split(text)

    assert any(c.metadata.get("chunk_type") == "table_candidate" for c in chunks)
    assert any("Stage I" in c.text for c in chunks)


def test_document_aware_chunker_falls_back_to_chinese_character_chunks() -> None:
    text = "\u8fd9\u662f\u4e00\u6bb5\u6ca1\u6709\u7a7a\u683c\u7684\u4e2d\u6587\u76f4\u64ad\u7a3f\u5185\u5bb9\u3002" * 120

    chunks = DocumentAwareChunker(chunk_size=180, chunk_overlap=30).split(text)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 180 for chunk in chunks)
    assert chunks[0].metadata["document_type"] == "live_script"
    assert chunks[0].metadata["chunk_strategy"] == "char_cn"
