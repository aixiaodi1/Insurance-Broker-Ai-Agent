from dataclasses import dataclass, field
import sys
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from strenum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStage(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    WRITING = "writing"
    DONE = "done"


class QualityWarning(StrEnum):
    EMPTY_PAGE = "empty_page"
    HEADER_FOOTER_DETECTED = "header_footer_detected"
    TABLE_CANDIDATE = "table_candidate"
    OCR_NEEDED = "ocr_needed"
    LOW_TEXT_DENSITY = "low_text_density"
    BROKEN_WORDS = "broken_words"
    PAGE_NUMBER_POLLUTION = "page_number_pollution"
    LOW_CLAUSE_RECOGNITION = "low_clause_recognition"


class ParserType(StrEnum):
    PYMUPDF = "PyMuPDF"
    PYPDF = "pypdf"
    TEXT = "text"
    MARKDOWN = "markdown"
    OCR = "ocr"


class QueryIntent(StrEnum):
    CLAIM_CALCULATION = "claim_calculation"
    BENEFIT_QUERY = "benefit_query"
    DISEASE_DEFINITION = "disease_definition"
    EXCLUSION_QUERY = "exclusion_query"
    WAITING_PERIOD = "waiting_period"
    AGE_RULE = "age_rule"
    CLAIM_MATERIALS = "claim_materials"
    COMPARISON_QUERY = "comparison_query"
    SUMMARY_QUERY = "summary_query"
    GENERAL = "general"


class ParseStatus(StrEnum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    filename: str
    collection: str
    status: DocumentStatus
    mime_type: str
    file_size: int
    source_path: str
    text_path: str | None
    content_hash: str
    chunk_count: int
    error: str | None
    created_at: str
    indexed_at: str | None


@dataclass(frozen=True)
class JobRecord:
    id: str
    rq_job_id: str | None
    document_id: str
    collection: str
    status: JobStatus
    stage: JobStage
    progress: int
    error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    token_count: int
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedLine:
    text: str
    page_num: int
    block_num: int
    line_num: int
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class CalculationRecord:
    id: str
    run_id: str | None
    thread_id: str | None
    user_id: str | None
    collection: str | None
    active_document_id: str | None
    intent: str | None
    formula: str | None
    input_vars_json: str | None
    missing_vars_json: str | None
    result_json: str | None
    rule_refs_json: str | None
    answer: str | None
    created_at: str


@dataclass(frozen=True)
class ParseReport:
    parser_name: str
    parse_status: ParseStatus
    quality_score: float
    total_pages: int
    total_lines: int
    selected_parser: ParserType
    parser_candidates: list[dict] = field(default_factory=list)
    warnings: list[QualityWarning] = field(default_factory=list)
    needs_ocr: bool = False
    quality_warnings: list[str] = field(default_factory=list)
    parsed_clean_path: str | None = None
    raw_lines_path: str | None = None
    report_path: str | None = None
