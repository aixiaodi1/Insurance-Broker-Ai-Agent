import re
from collections.abc import Iterable

from app.domain import TextChunk


_CHINESE_NUMERALS = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u96f6"
_CLAUSE_HEADING_RE = re.compile(f"(?m)^\\s*(\\u7b2c[{_CHINESE_NUMERALS}\\d]+\\u6761\\s+[^\\n\\r]+)")
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


class DocumentAwareChunker:
    """Routes insurance documents to specialized chunking before falling back."""

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
            chunks = self._split_by_headings(
                normalized_text,
                heading_pattern=_CLAUSE_HEADING_RE,
                document_type="insurance_clause",
                chunk_strategy="insurance_clause",
                chunk_type="clause",
                title_key="clause_title",
            )
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
        if _CLAUSE_HEADING_RE.search(text) and _contains_any(text, _INSURANCE_SIGNALS):
            return "insurance_clause"
        if _CASE_HEADING_RE.search(text) and _contains_any(text, _CLAIM_CASE_SIGNALS):
            return "claim_case"
        if _contains_any(text, _LIVE_SCRIPT_SIGNALS):
            return "live_script"
        return "generic_document"

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
            metadata = {
                "document_type": document_type,
                "chunk_strategy": chunk_strategy,
                "chunk_type": chunk_type,
                "section_title": title,
                title_key: title,
                "fallback_level": 0,
            }
            chunks.extend(self._split_long_text(section_text, metadata))

        return chunks

    def _split_long_text(self, text: str, metadata: dict[str, str | int | float | bool | None]) -> list[TextChunk]:
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
