from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "id",
    "task",
    "environment",
    "reference",
    "case_type",
    "required_behaviors",
    "forbidden_behaviors",
    "rubric",
    "transcript_review_notes",
}


def load_scenarios(path: Path | str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Evaluation scenarios must be a JSON list")
    seen: set[str] = set()
    for scenario in payload:
        if not isinstance(scenario, dict) or not REQUIRED_FIELDS.issubset(scenario):
            raise ValueError("Every evaluation scenario must contain the complete schema")
        if scenario["id"] in seen:
            raise ValueError(f"Duplicate evaluation id: {scenario['id']}")
        if scenario["case_type"] not in {"positive", "negative"}:
            raise ValueError(f"Invalid case type: {scenario['case_type']}")
        seen.add(str(scenario["id"]))
    return payload


def evaluate_transcript(scenario: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    event_types = [str(event.get("type")) for event in transcript.get("events", []) if isinstance(event, dict)]
    required = [str(value) for value in scenario.get("required_behaviors", [])]
    forbidden = [str(value) for value in scenario.get("forbidden_behaviors", [])]
    missing_required = [value for value in required if value not in event_types]
    forbidden_seen = [value for value in forbidden if value in event_types]
    required_score = 1.0 if not required else (len(required) - len(missing_required)) / len(required)
    boundary_score = 1.0 if not forbidden_seen else 0.0
    behavior_score = (required_score + boundary_score) / 2

    answer = str(transcript.get("final_answer") or "").lower()
    keywords = [str(value).lower() for value in (scenario.get("reference") or {}).get("keywords", [])]
    answer_score = 1.0 if not keywords else sum(keyword in answer for keyword in keywords) / len(keywords)
    rubric = scenario.get("rubric") or {}
    behavior_weight = float(rubric.get("behavior", 0.7))
    answer_weight = float(rubric.get("answer", 0.3))
    total_weight = behavior_weight + answer_weight or 1.0
    score = round((behavior_score * behavior_weight + answer_score * answer_weight) / total_weight, 4)
    return {
        "id": scenario["id"],
        "score": score,
        "passed": score >= 0.8 and not missing_required and not forbidden_seen,
        "missing_required": missing_required,
        "forbidden_seen": forbidden_seen,
        "answer_keyword_coverage": round(answer_score, 4),
        "event_types": event_types,
    }


def write_evaluation_report(
    cases: list[tuple[dict[str, Any], dict[str, Any]]], output_dir: Path | str
) -> dict[str, Any]:
    output = Path(output_dir)
    failures = output / "failures"
    failures.mkdir(parents=True, exist_ok=True)
    results = []
    for scenario, transcript in cases:
        result = evaluate_transcript(scenario, transcript)
        results.append(result)
        if not result["passed"]:
            (failures / f"{scenario['id']}.json").write_text(
                json.dumps({"scenario": scenario, "transcript": transcript, "result": result}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    pass_rate = sum(result["passed"] for result in results) / len(results) if results else 0.0
    report = {
        "scenario_count": len(results),
        "pass_rate": round(pass_rate, 4),
        "saturated": len(results) >= 20 and pass_rate >= 0.95,
        "results": results,
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
