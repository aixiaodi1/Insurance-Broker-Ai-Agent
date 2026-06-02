import json
import re
from collections import Counter
from pathlib import Path

from app.domain import (
    ParseReport,
    ParseStatus,
    ParsedLine,
    ParserType,
    QualityWarning,
)
from app.errors import NonRetryableIngestionError
from app.observability import get_logger

logger = get_logger(__name__)

_CLAUSE_TITLE_RE = re.compile(r"^\s*(?:\d{1,2}\.\d+(?:\.\d+)*)\s+\S")
_PAGE_NUM_RE = re.compile(r"^\s*[-–—]?\s*\d{1,3}\s*[-–—]?\s*$")
_CHINESE_PAGE_NUM_RE = re.compile(r"^\s*[-–—]?\s*第?\s*[\d○一二三四五六七八九十百千]+\s*页?\s*[-–—]?\s*$")
_HEADER_FOOTER_MIN_PAGES = 3


class PdfParserV2:
    """PDF parser based on PyMuPDF (fitz).

    Extracts text with coordinate-level detail, cleans headers/footers,
    fixes Chinese word breaks, detects clause titles and table candidates,
    and produces an auditable parse report.
    """

    def __init__(self) -> None:
        self._total_pages = 0
        self._total_lines = 0
        self._all_lines: list[ParsedLine] = []
        self._page_line_counts: list[int] = []
        self._potential_headers: dict[str, list[int]] = {}
        self._potential_footers: dict[str, list[int]] = {}
        self._quality_warnings: list[QualityWarning] = []
        self._quality_warning_messages: list[str] = []
        self._table_line_count = 0
        self._clause_title_count = 0
        self._broken_word_fixes = 0

    def parse(self, path: Path) -> str:
        text, report = self._do_parse(path)
        self._save_sidecar(path, text, report)
        return text

    def parse_with_report(self, path: Path) -> tuple[str, ParseReport]:
        text, report = self._do_parse(path)
        self._save_sidecar(path, text, report)
        return text, report

    def _do_parse(self, path: Path) -> tuple[str, ParseReport]:
        self._reset()
        try:
            import fitz
        except ImportError:
            raise NonRetryableIngestionError("PyMuPDF (fitz) is not installed. Add 'PyMuPDF' to dependencies.")

        try:
            doc = fitz.open(str(path))
        except Exception as exc:
            raise NonRetryableIngestionError(f"Failed to open PDF with PyMuPDF: {exc}")

        self._total_pages = len(doc)
        for page_num, page in enumerate(doc, start=1):
            if page_num > 1:
                self._all_lines.append(ParsedLine(
                    text="\f",
                    page_num=page_num,
                    block_num=0,
                    line_num=-1,
                    bbox=(0, 0, 0, 0),
                ))
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            line_count = 0
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    line_text = "".join(span["text"] for span in spans).strip()
                    if not line_text:
                        continue
                    bbox = tuple(round(v, 1) for v in line["bbox"])
                    self._all_lines.append(ParsedLine(
                        text=line_text,
                        page_num=page_num,
                        block_num=block.get("number", 0),
                        line_num=line_count,
                        bbox=bbox,
                    ))
                    line_count += 1
            self._page_line_counts.append(line_count)

        doc.close()
        self._total_lines = len(self._all_lines)

        if self._total_lines == 0:
            self._quality_warnings.append(QualityWarning.EMPTY_PAGE)
            self._quality_warning_messages.append("No text extracted from PDF")
            report = self._build_report_path(Path(path))
            return "", report

        raw_lines_text = "\n".join(ln.text for ln in self._all_lines)
        text, report = self._clean_and_report(path, raw_lines_text)
        return text, report

    def _clean_and_report(self, path: Path, raw_text: str) -> tuple[str, ParseReport]:
        lines = raw_text.split("\n")
        cleaned_lines, clause_count, table_count, broken_fixes = self._clean_lines(lines)
        clause_titles = self._count_clause_titles(cleaned_lines)
        self._clause_title_count = clause_titles
        self._table_line_count = table_count
        self._broken_word_fixes = broken_fixes

        cleaned_text = "\n".join(cleaned_lines).strip()
        quality_score = self._compute_quality_score(clause_titles, table_count, broken_fixes)
        needs_ocr = self._detect_needs_ocr(lines, quality_score)
        report_text = self._build_report(path, quality_score, needs_ocr)

        if needs_ocr:
            self._quality_warnings.append(QualityWarning.OCR_NEEDED)
            self._quality_warning_messages.append("Low text density; may be scanned document")
        if table_count > 5:
            self._quality_warnings.append(QualityWarning.TABLE_CANDIDATE)
            self._quality_warning_messages.append(f"Detected {table_count} table-candidate lines")
        if broken_fixes > 10:
            self._quality_warnings.append(QualityWarning.BROKEN_WORDS)
            self._quality_warning_messages.append(f"Fixed {broken_fixes} broken Chinese words")
        if clause_titles == 0:
            self._quality_warnings.append(QualityWarning.LOW_CLAUSE_RECOGNITION)
            self._quality_warning_messages.append("No clause titles detected")

        report = self._build_report(path, quality_score, needs_ocr)
        return cleaned_text, report

    def _clean_lines(self, lines: list[str]) -> tuple[list[str], int, int, int]:
        page_lines = self._group_lines_by_page(lines)
        headers, footers = self._detect_headers_footers(page_lines)

        cleaned: list[str] = []
        clause_count = 0
        table_count = 0
        broken_word_fixes = 0
        prev_line_ended = False

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                cleaned.append("")
                continue

            if stripped == "\f":
                cleaned.append(stripped)
                prev_line_ended = True
                continue

            if self._is_page_number(stripped) and self._is_isolated_page_number(line, i, cleaned):
                cleaned.append("")
                continue

            if headers and stripped in headers:
                cleaned.append("")
                continue
            if footers and stripped in footers:
                cleaned.append("")
                continue

            fixed, fixes = self._fix_broken_words(stripped)
            broken_word_fixes += fixes

            if _CLAUSE_TITLE_RE.match(fixed):
                clause_count += 1
                if cleaned and cleaned[-1] != "":
                    cleaned.append("")
                cleaned.append(fixed)
                cleaned.append("")
                prev_line_ended = False
                continue

            if self._is_table_line(fixed, line):
                table_count += 1
                cleaned.append(fixed)
                prev_line_ended = False
                continue

            if prev_line_ended and not self._is_sentence_end(fixed, cleaned):
                cleaned[-1] = self._merge_lines(cleaned[-1], fixed)
            else:
                cleaned.append(fixed)
            prev_line_ended = not self._is_sentence_end(fixed, cleaned)

        return cleaned, clause_count, table_count, broken_word_fixes

    def _group_lines_by_page(self, lines: list[str]) -> list[list[str]]:
        page_groups: list[list[str]] = []
        page_breaks = [i for i, l in enumerate(lines) if l.strip() == "\f"]
        idx = 0
        for pb in page_breaks:
            page_groups.append(lines[idx:pb])
            idx = pb + 1
        if idx < len(lines):
            page_groups.append(lines[idx:])
        return page_groups or [lines]

    def _detect_headers_footers(
        self, page_lines: list[list[str]]
    ) -> tuple[set[str], set[str]]:
        if len(page_lines) < _HEADER_FOOTER_MIN_PAGES:
            return set(), set()

        first_lines: list[str] = []
        last_lines: list[str] = []
        for page in page_lines:
            non_empty = [l.strip() for l in page if l.strip()]
            if non_empty:
                first_lines.append(non_empty[0])
                last_lines.append(non_empty[-1])

        header_candidates = [
            t for t, c in Counter(first_lines).most_common(3)
            if c >= _HEADER_FOOTER_MIN_PAGES - 1 and len(t) < 60
        ]
        footer_candidates = [
            t for t, c in Counter(last_lines).most_common(3)
            if c >= _HEADER_FOOTER_MIN_PAGES - 1 and len(t) < 60
        ]

        return set(header_candidates), set(footer_candidates)

    def _is_page_number(self, text: str) -> bool:
        if _PAGE_NUM_RE.match(text):
            return True
        if _CHINESE_PAGE_NUM_RE.match(text):
            return True
        return False

    def _is_isolated_page_number(self, text: str, idx: int, cleaned: list[str]) -> bool:
        if len(text) > 10:
            return False
        context_before = cleaned[-1] if cleaned else ""
        context_after = ""
        if re.search(r"[\u4e00-\u9fff\w]", context_before) and len(context_before.strip()) > 5:
            return False
        return True

    def _fix_broken_words(self, text: str) -> tuple[str, int]:
        fixes = 0
        fixed = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", lambda m: m.group(1) + m.group(2), text)
        if fixed != text:
            fixes = 1
        fixed = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", lambda m: m.group(1) + m.group(2), fixed)
        fixed = fixed.replace("  ", " ")
        return fixed.strip(), fixes

    def _is_table_line(self, text: str, raw_line: str) -> bool:
        if re.search(r"\d+[xX×]\d+", text) and len(text) < 100:
            return True
        if re.search(r"\b(?:TNM|I{1,3}[A-Z]?|Stage\s+[IVX]+)\b", text, re.IGNORECASE):
            return True
        pipe_count = text.count("|")
        if pipe_count >= 3:
            return True
        space_clusters = len(re.findall(r"\s{3,}", raw_line))
        if space_clusters >= 2 and len(text) < 80:
            return True
        return False

    def _is_sentence_end(self, text: str, cleaned: list[str]) -> bool:
        if not text:
            return True
        stripped = text.rstrip()
        if stripped and stripped[-1] in ("。", "！", "？", "；", ".", "!", "?", ";", "："):
            return True
        if _CLAUSE_TITLE_RE.match(stripped):
            return True
        if cleaned and cleaned[-1].strip().endswith("："):
            return True
        return False

    def _merge_lines(self, prev: str, next_line: str) -> str:
        if not prev:
            return next_line
        if not next_line:
            return prev
        prev_text = prev.rstrip()
        next_text = next_line.lstrip()
        if prev_text and re.search(r"[\u4e00-\u9fff]$", prev_text):
            return prev_text + next_text
        if prev_text and re.search(r"[\u4e00-\u9fff]$", prev_text) and next_text and re.search(r"^[\u4e00-\u9fff]", next_text):
            return prev_text + next_text
        return prev_text + " " + next_text

    def _compute_quality_score(
        self, clause_titles: int, table_count: int, broken_fixes: int
    ) -> float:
        score = 1.0
        if self._total_pages == 0:
            return 0.0
        density = self._total_lines / max(self._total_pages, 1)
        if density < 5:
            score -= 0.4
        elif density < 15:
            score -= 0.2
        if clause_titles == 0 and self._total_lines > 30:
            score -= 0.3
        if broken_fixes > 20:
            score -= 0.2
        elif broken_fixes > 10:
            score -= 0.1
        if table_count > 20:
            score -= 0.1
        score = max(0.0, min(1.0, score))
        return round(score, 2)

    def _detect_needs_ocr(self, lines: list[str], quality_score: float) -> bool:
        if self._total_lines < 10:
            return True
        avg_line_len = sum(len(l) for l in lines) / max(len(lines), 1)
        if avg_line_len < 10 and quality_score < 0.4:
            return True
        return False

    def _count_clause_titles(self, lines: list[str]) -> int:
        count = 0
        for line in lines:
            if _CLAUSE_TITLE_RE.match(line.strip()):
                count += 1
        return count

    def _build_report(self, path: Path, quality_score: float, needs_ocr: bool) -> ParseReport:
        warnings = list(self._quality_warnings)
        parse_status = ParseStatus.WARNING if warnings else ParseStatus.SUCCESS
        return ParseReport(
            parser_name="PdfParserV2",
            parse_status=parse_status,
            quality_score=quality_score,
            total_pages=self._total_pages,
            total_lines=self._total_lines,
            selected_parser=ParserType.PYMUPDF,
            parser_candidates=[
                {"parser": "PyMuPDF", "quality_score": quality_score},
            ],
            warnings=warnings,
            needs_ocr=needs_ocr,
            quality_warnings=self._quality_warning_messages,
        )

    def _build_report_path(self, path: Path) -> ParseReport:
        return ParseReport(
            parser_name="PdfParserV2",
            parse_status=ParseStatus.FAILED,
            quality_score=0.0,
            total_pages=self._total_pages,
            total_lines=0,
            selected_parser=ParserType.PYMUPDF,
            warnings=[QualityWarning.EMPTY_PAGE],
            needs_ocr=False,
            quality_warnings=["No text extracted"],
        )

    def _save_sidecar(self, pdf_path: Path, cleaned_text: str, report: ParseReport) -> None:
        base = pdf_path.parent
        try:
            raw_lines = [
                {
                    "text": ln.text,
                    "page": ln.page_num,
                    "block": ln.block_num,
                    "line": ln.line_num,
                    "bbox": list(ln.bbox) if ln.bbox else None,
                }
                for ln in self._all_lines
            ]
            raw_lines_path = base / "raw_lines.json"
            raw_lines_path.write_text(json.dumps(raw_lines, ensure_ascii=False, indent=2), encoding="utf-8")

            clean_path = base / "parsed_clean.md"
            clean_path.write_text(cleaned_text, encoding="utf-8")

            report_dict = {
                "parser_name": report.parser_name,
                "parse_status": report.parse_status,
                "quality_score": report.quality_score,
                "total_pages": report.total_pages,
                "total_lines": report.total_lines,
                "selected_parser": report.selected_parser,
                "parser_candidates": report.parser_candidates,
                "warnings": [str(w) for w in report.warnings],
                "needs_ocr": report.needs_ocr,
                "quality_warnings": report.quality_warnings,
            }
            report_path = base / "parse_report.json"
            report_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")

            object.__setattr__(report, "raw_lines_path", str(raw_lines_path))
            object.__setattr__(report, "parsed_clean_path", str(clean_path))
            object.__setattr__(report, "report_path", str(report_path))
        except OSError as exc:
            logger.warning("sidecar_save_failed", extra={"extra_fields": {"path": str(base), "error": str(exc)}})

    def _reset(self) -> None:
        self._total_pages = 0
        self._total_lines = 0
        self._all_lines = []
        self._page_line_counts = []
        self._potential_headers = {}
        self._potential_footers = {}
        self._quality_warnings = []
        self._quality_warning_messages = []
        self._table_line_count = 0
        self._clause_title_count = 0
        self._broken_word_fixes = 0
