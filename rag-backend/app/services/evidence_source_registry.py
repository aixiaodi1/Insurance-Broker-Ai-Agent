import json
import re
from pathlib import Path
from typing import Any


class EvidenceSourceRegistry:
    def __init__(self, data_dir: Path | str, max_matches: int = 5) -> None:
        self._data_dir = Path(data_dir)
        self._max_matches = max_matches
        self._company_specs: list[dict[str, Any]] | None = None
        self._pdf_links: list[dict[str, Any]] | None = None

    def query(self, prompt: str) -> dict[str, Any]:
        if not self._data_dir.exists():
            return {
                "enabled": False,
                "dataDir": str(self._data_dir),
                "companyMatches": [],
                "materialMatches": [],
                "summary": "Evidence source registry data directory is not available.",
            }

        company_matches = self._match_company_specs(prompt)
        material_matches = self._match_pdf_links(prompt)
        summary = (
            f"Matched {len(company_matches)} company source entries and "
            f"{len(material_matches)} official material candidates."
        )
        return {
            "enabled": True,
            "dataDir": str(self._data_dir),
            "companyMatches": company_matches,
            "materialMatches": material_matches,
            "summary": summary,
        }

    def _match_company_specs(self, prompt: str) -> list[dict[str, Any]]:
        scored_matches = []
        for spec in self._load_company_specs():
            company = _first_text(spec, "company", "company_name", "name_zh")
            if not company:
                continue
            spec_file = str(spec.get("_source_file", ""))
            haystack = f"{company} {spec_file}"
            if _has_token_overlap(prompt, haystack):
                scored_matches.append(
                    (
                        _match_score(prompt, company, ""),
                        {
                            "company": company,
                            "officialUrl": _first_text(spec, "official_url", "source_url", "disclosure_url"),
                            "crawlMethod": _first_text(spec, "crawl_method"),
                            "pdfHost": _first_text(spec, "pdf_host"),
                            "productCount": _first_int(spec, "product_count", "total_products"),
                            "pdfCount": _first_int(spec, "pdf_count", "total_pdf_links"),
                            "sourceFile": spec_file,
                            "sourceTier": "S2_OFFICIAL_SPEC",
                        },
                    )
                )
        scored_matches.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored_matches[: self._max_matches]]

    def _match_pdf_links(self, prompt: str) -> list[dict[str, Any]]:
        scored_matches = []
        for row in self._load_pdf_links():
            company = str(row.get("company") or "")
            product_name = str(row.get("product_name") or "")
            haystack = f"{company} {product_name} {row.get('file_type') or ''}"
            if _has_token_overlap(prompt, haystack):
                scored_matches.append(
                    (
                        _match_score(prompt, company, product_name),
                        {
                            "company": company,
                            "productName": product_name,
                            "status": str(row.get("status") or ""),
                            "materialType": str(row.get("file_type") or ""),
                            "url": str(row.get("url") or ""),
                            "extension": str(row.get("extension") or ""),
                            "sourceFile": str(row.get("source_file") or ""),
                            "sourceKind": str(row.get("source_kind") or ""),
                            "sourceTier": _material_source_tier(row),
                        },
                    )
                )
        scored_matches.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored_matches[: self._max_matches]]

    def _load_company_specs(self) -> list[dict[str, Any]]:
        if self._company_specs is not None:
            return self._company_specs

        specs_dir = self._data_dir / "insurance_harness" / "specs"
        specs = []
        if specs_dir.exists():
            for path in sorted(specs_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict):
                    specs.append({**data, "_source_file": path.name})
        self._company_specs = specs
        return specs

    def _load_pdf_links(self) -> list[dict[str, Any]]:
        if self._pdf_links is not None:
            return self._pdf_links

        jsonl_path = self._data_dir / "insurance_harness" / "cleaned" / "pdf_download_links.jsonl"
        links = []
        if jsonl_path.exists():
            with jsonl_path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict):
                        links.append(data)
        self._pdf_links = links
        return links


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _first_int(data: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _has_token_overlap(prompt: str, text: str) -> bool:
    prompt_tokens = _tokens(prompt)
    text_tokens = _tokens(text)
    if not prompt_tokens or not text_tokens:
        return False
    return any(token in text for token in prompt_tokens) or any(token in prompt for token in text_tokens)


def _tokens(value: str) -> list[str]:
    raw_tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", value.lower())
    tokens = []
    for token in raw_tokens:
        if len(token) >= 2:
            tokens.append(token)
        if len(token) >= 4 and re.search(r"[\u4e00-\u9fff]", token):
            for start in range(0, len(token) - 1):
                tokens.append(token[start : start + 2])
    return tokens


def _match_score(prompt: str, company: str, product_name: str) -> int:
    score = 0
    if company and any(token in prompt for token in _tokens(company)):
        score += 100
    product_tokens = set(_tokens(product_name))
    prompt_tokens = set(_tokens(prompt))
    score += len(product_tokens & prompt_tokens) * 10
    if product_name and product_name in prompt:
        score += 200
    return score


def _material_source_tier(row: dict[str, Any]) -> str:
    if str(row.get("extension") or "").lower() == "pdf" and str(row.get("source_kind") or "") == "explicit":
        return "S1_OFFICIAL_PDF"
    return "S2_OFFICIAL_MATERIAL"
