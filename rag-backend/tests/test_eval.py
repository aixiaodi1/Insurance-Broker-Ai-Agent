import json
from pathlib import Path


def _load_qa(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_golden_qa_dataset_is_valid_json() -> None:
    qa_path = Path(__file__).resolve().parent.parent / "data" / "evals" / "golden_qa.json"
    assert qa_path.exists(), f"Golden QA file not found: {qa_path}"
    questions = _load_qa(qa_path)
    assert len(questions) >= 15, f"Expected at least 15 questions, got {len(questions)}"


def test_golden_qa_dataset_structure() -> None:
    qa_path = Path(__file__).resolve().parent.parent / "data" / "evals" / "golden_qa.json"
    questions = _load_qa(qa_path)

    required_fields = {"id", "category", "question", "must_retrieve", "answer_contains", "must_not_contain", "must_cite_sections", "notes"}
    valid_categories = {"waiting_period", "benefit_query", "disease_definition", "exclusion_query", "age_rule", "claim_materials", "summary_query"}

    seen_ids = set()
    for q in questions:
        assert required_fields.issubset(q.keys()), f"Question {q.get('id', '?')} missing fields: {required_fields - q.keys()}"
        assert q["id"] not in seen_ids, f"Duplicate question id: {q['id']}"
        seen_ids.add(q["id"])
        assert q["category"] in valid_categories, f"Question {q['id']} has invalid category: {q['category']}"
        assert isinstance(q["must_retrieve"], list), f"must_retrieve must be a list"
        assert isinstance(q["answer_contains"], list), f"answer_contains must be a list"
        assert isinstance(q["must_not_contain"], list), f"must_not_contain must be a list"
        assert isinstance(q["must_cite_sections"], list), f"must_cite_sections must be a list"


def test_golden_qa_category_coverage() -> None:
    qa_path = Path(__file__).resolve().parent.parent / "data" / "evals" / "golden_qa.json"
    questions = _load_qa(qa_path)

    categories = {q["category"] for q in questions}
    required = {"waiting_period", "benefit_query", "disease_definition", "exclusion_query", "claim_materials"}
    missing = required - categories
    assert not missing, f"Missing required categories: {missing}"
