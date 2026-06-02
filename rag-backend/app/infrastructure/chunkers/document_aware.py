import re
from collections.abc import Iterable

from app.domain import TextChunk

_CHINESE_NUMERALS = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u96f6"
_CHINESE_CLAUSE_RE = re.compile(f"(?m)^\\s*(\\u7b2c[{_CHINESE_NUMERALS}\\d]+\\u6761\\s+[^\\n\\r]+)")
_NUMBERED_CLAUSE_RE = re.compile(r"(?m)^\s*(\d{1,2}\.\d+(?:\.\d+)*)\s+(\S[^\n]*)")
_CASE_HEADING_RE = re.compile(f"(?m)^\\s*(\\u6848\\u4f8b[{_CHINESE_NUMERALS}\\d]+[\\uff1a:][^\\n\\r]*)")
_LIVE_SCRIPT_SIGNALS = (
    "\u76f4\u64ad",
    "\u53e3\u64ad",
    "\u5927\u5bb6\u597d",
    "\u4eca\u5929\u6211\u4eec",
    "\u5173\u6ce8\u6211",
)
_INSURANCE_SIGNALS = (
    "\u4fdd\u9669\u6761\u6b3e",
    "\u4fdd\u9669\u8d23\u4efb",
    "\u8d23\u4efb\u514d\u9664",
    "\u7b49\u5f85\u671f",
    "\u4fdd\u9669\u91d1\u7533\u8bf7",
    "\u6295\u4fdd\u8303\u56f4",
)
_CLAIM_CASE_SIGNALS = (
    "\u62d2\u8d54",
    "\u7406\u8d54\u6848\u4f8b",
    "\u62d2\u8d54\u6848\u4f8b",
    "\u62d2\u8d54\u539f\u56e0",
    "\u6848\u4f8b\u4e00",
    "\u6848\u4f8b\u4e8c",
)
_SENTENCE_SPLIT_RE = re.compile("(?<=[\u3002\uff01\uff1f!?;；])\\s*|\\n+")

_CONTENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "insurance_liability": ("\u4fdd\u9669\u91d1", "\u4fdd\u9669\u8d23\u4efb", "\u7ed9\u4ed8", "\u8d54\u507f", "\u4fdd\u969c\u8303\u56f4"),
    "exclusion": ("\u8d23\u4efb\u514d\u9664", "\u4e0d\u627f\u62c5", "\u514d\u8d23", "\u9664\u5916", "\u4e0d\u8d54"),
    "waiting_period": ("\u7b49\u5f85\u671f", "\u89c2\u5bdf\u671f"),
    "disease_definition": (
        "\u75be\u75c5\u5b9a\u4e49", "\u91cd\u5927\u75be\u75c5", "\u8f7b\u5ea6\u75be\u75c5", "\u5b9a\u4e49",
        "\u6076\u6027\u80bf\u7624", "\u539f\u4f4d\u764c", "\u6025\u6027", "\u91cd\u5ea6",
        "\u7b2c\u4e00\u6b21", "\u4e2d\u98ce", "\u5fc3\u808c\u6800\u6b7b", "\u51a0\u72b6\u52a8\u8109",
        "\u80bf\u7624", "\u764c", "\u7ec6\u80de\u75ca\u53d8", "\u7ec6\u80de\u589e\u6b96",
        "\u60a3\u8005", "\u75c7\u72b6", "\u7eb3\u5c55",
    ),
    "claim_material": ("\u7406\u8d54", "\u7533\u8bf7", "\u6750\u6599", "\u8d44\u6599", "\u7406\u8d54\u91d1\u7533\u8bf7"),
    "definition": ("\u91ca\u4e49", "\u89e3\u91ca", "\u540d\u8bcd\u89e3\u91ca"),
    "premium": ("\u4fdd\u8d39", "\u7f34\u8d39", "\u8d39\u7387"),
    "age_rule": ("\u5e74\u9f84", "\u5468\u5c81", "\u4fdd\u5355\u5e74\u5ea6"),
}

_TABLE_SIGNALS = (
    "\u5206\u671f",  # staging
    "TNM",
    "Stage",
    "|",
)


class DocumentAwareChunker:
    """Routes insurance documents to specialized chunking before falling back.

    PR-2: Clause-number-aware chunking with content_type classification.
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be greater than or equal to 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str) -> list[TextChunk]:
        normalized_text = _normalize_text(text)
        if not normalized_text:
            raise ValueError("Cannot chunk empty text")

        route = self._route(normalized_text)
        if route == "insurance_clause":
            chunks = self._split_insurance(normalized_text)
            if chunks:
                return self._reindex(chunks)

        if route == "claim_case":
            chunks = self._split_by_headings(
                normalized_text,
                heading_pattern=_CASE_HEADING_RE,
                document_type="claim_case",
                chunk_strategy="claim_case",
                chunk_type="case",
                title_key="section_title",
            )
            if chunks:
                return self._reindex(chunks)

        document_type = "live_script" if route == "live_script" else "generic_document"
        return self._reindex(
            self._split_long_text(
                normalized_text,
                {
                    "document_type": document_type,
                    "chunk_strategy": "char_cn",
                    "chunk_type": "fallback",
                    "fallback_level": 3,
                },
            )
        )

    def _route(self, text: str) -> str:
        if (_CHINESE_CLAUSE_RE.search(text) or _NUMBERED_CLAUSE_RE.search(text)) and _contains_any(text, _INSURANCE_SIGNALS):
            return "insurance_clause"
        if _CASE_HEADING_RE.search(text) and _contains_any(text, _CLAIM_CASE_SIGNALS):
            return "claim_case"
        if _contains_any(text, _LIVE_SCRIPT_SIGNALS):
            return "live_script"
        return "generic_document"

    def _split_insurance(self, text: str) -> list[TextChunk]:
        boundaries = self._find_clause_boundaries(text)
        if not boundaries:
            return []

        chunks: list[TextChunk] = []
        for index, (start, end) in enumerate(boundaries):
            section_text = text[start:end].strip()
            if not section_text:
                continue

            first_line = section_text.split("\n")[0].strip()
            section_no = _extract_section_no(first_line) or ""
            section_title = first_line[:120]
            content_type = _classify_content_type(section_title)

            chunk_type = "clause"
            if content_type == "exclusion":
                chunk_type = "exclusion"
            elif content_type == "disease_definition":
                chunk_type = "disease_definition"
            elif content_type == "claim_material":
                chunk_type = "claim_material"
            elif content_type == "definition":
                chunk_type = "definition"

            metadata = {
                "document_type": "insurance_clause",
                "chunk_strategy": "insurance_clause",
                "chunk_type": chunk_type,
                "section_no": section_no,
                "section_title": section_title,
                "clause_title": section_title,
                "content_type": content_type,
                "fallback_level": 0,
            }

            chunks.extend(self._split_long_text(section_text, metadata))

        return chunks

    def _find_clause_boundaries(self, text: str) -> list[tuple[int, int]]:
        boundaries: list[tuple[int, str, int]] = []

        for match in _CHINESE_CLAUSE_RE.finditer(text):
            boundaries.append((match.start(), "chinese", match.end()))

        for match in _NUMBERED_CLAUSE_RE.finditer(text):
            boundaries.append((match.start(), "numbered", match.end()))

        boundaries.sort(key=lambda x: x[0])

        deduped: list[tuple[int, int]] = []
        for start, btype, _ in boundaries:
            if deduped and start < deduped[-1][1]:
                continue
            deduped.append((start, 0))

        result: list[tuple[int, int]] = []
        for i, (start, _) in enumerate(deduped):
            end = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
            result.append((start, end))

        return result

    def _split_by_headings(
        self,
        text: str,
        heading_pattern: re.Pattern[str],
        document_type: str,
        chunk_strategy: str,
        chunk_type: str,
        title_key: str,
    ) -> list[TextChunk]:
        matches = list(heading_pattern.finditer(text))
        chunks: list[TextChunk] = []

        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            if not section_text:
                continue

            title = match.group(1).strip()
            section_title = _extract_section_title(title) or title[:60]
            section_no = _extract_section_no(title) or ""
            content_type = _classify_content_type(section_title)

            metadata = {
                "document_type": document_type,
                "chunk_strategy": chunk_strategy,
                "chunk_type": chunk_type,
                "section_title": title,
                "section_no": section_no,
                "content_type": content_type,
                title_key: title,
                "fallback_level": 0,
            }
            chunks.extend(self._split_long_text(section_text, metadata))

        return chunks

    def _split_long_text(self, text: str, metadata: dict[str, str | int | float | bool | None]) -> list[TextChunk]:
        has_table = _is_table_section(text)
        if has_table:
            table_meta = {**metadata, "chunk_type": "table_candidate", "content_type": "table_candidate", "fallback_level": 0}
            return [
                TextChunk(
                    chunk_index=0,
                    text=text.strip(),
                    token_count=_estimated_token_count(text),
                    metadata=table_meta,
                )
            ]

        units = _split_sentence_units(text)
        chunks: list[TextChunk] = []
        current = ""

        for unit in units:
            if not current:
                current = unit
                continue

            separator = "" if _is_cjk_text(current[-1:]) or _is_cjk_text(unit[:1]) else " "
            candidate = f"{current}{separator}{unit}"
            if _estimated_token_count(candidate) <= self.chunk_size:
                current = candidate
                continue

            chunks.extend(self._hard_split(current, metadata))
            current = unit

        if current:
            chunks.extend(self._hard_split(current, metadata))

        return chunks

    def _hard_split(self, text: str, metadata: dict[str, str | int | float | bool | None]) -> list[TextChunk]:
        if _estimated_token_count(text) <= self.chunk_size:
            return [
                TextChunk(
                    chunk_index=0,
                    text=text.strip(),
                    token_count=_estimated_token_count(text),
                    metadata={**metadata},
                )
            ]

        step = self.chunk_size - self.chunk_overlap
        chunks: list[TextChunk] = []
        for start in range(0, len(text), step):
            chunk_text = text[start : start + self.chunk_size].strip()
            if not chunk_text:
                break
            chunks.append(
                TextChunk(
                    chunk_index=0,
                    text=chunk_text,
                    token_count=_estimated_token_count(chunk_text),
                    metadata={**metadata, "fallback_level": max(int(metadata.get("fallback_level") or 0), 2)},
                )
            )
            if start + self.chunk_size >= len(text):
                break
        return chunks

    def dual_split(
        self,
        text: str,
        parent_chunk_size: int = 1500,
    ) -> tuple[list[TextChunk], list[TextChunk]]:
        parent_chunker = DocumentAwareChunker(
            chunk_size=parent_chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        parents = parent_chunker.split(text)
        children = self.split(text)
        return (parents, children)

    def _reindex(self, chunks: Iterable[TextChunk]) -> list[TextChunk]:
        return [
            TextChunk(
                chunk_index=index,
                text=chunk.text,
                token_count=chunk.token_count,
                metadata=chunk.metadata,
            )
            for index, chunk in enumerate(chunks)
        ]


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _split_sentence_units(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _estimated_token_count(text: str) -> int:
    if _is_cjk_text(text):
        return len(text)
    return len(text.split())


def _is_cjk_text(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(signal in text for signal in signals)


def _extract_section_no(line: str) -> str | None:
    m = _NUMBERED_CLAUSE_RE.match(line.strip())
    if m:
        return m.group(1)
    m = _CHINESE_CLAUSE_RE.match(line.strip())
    if m:
        raw = m.group(1)
        nums = re.findall(r"[\d" + _CHINESE_NUMERALS + r"]+", raw)
        return ".".join(nums) if nums else None
    return None


def _extract_section_title(line: str) -> str | None:
    m = _NUMBERED_CLAUSE_RE.match(line.strip())
    if m:
        return m.group(2).strip()
    m = _CHINESE_CLAUSE_RE.match(line.strip())
    if m:
        text = m.group(1)
        idx = text.find("\u6761")  # 条
        if idx != -1:
            return text[idx + 1:].strip()
        return text
    return line.strip()[:60] if line.strip() else None


def _classify_content_type(section_title: str) -> str:
    for content_type, keywords in _CONTENT_TYPE_KEYWORDS.items():
        if any(kw in section_title for kw in keywords):
            return content_type
    return "clause"


def _is_table_section(text: str) -> bool:
    lines = text.split("\n")
    if len(lines) < 3:
        return False
    table_count = 0
    for line in lines:
        stripped = line.strip()
        pipe_count = stripped.count("|")
        if pipe_count >= 2:
            table_count += 1
        elif re.search(r"\d+[xX×]\d+", stripped) and len(stripped) < 100:
            table_count += 1
        elif re.search(r"\b(TNM|Stage\s+[IVX]+)\b", stripped, re.IGNORECASE):
            table_count += 1
    return table_count >= max(2, len(lines) * 0.3)
