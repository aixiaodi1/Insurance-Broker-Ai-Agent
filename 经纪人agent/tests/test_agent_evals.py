import json
from pathlib import Path

from app.evals.runner import evaluate_transcript, load_scenarios, write_evaluation_report


def test_initial_eval_set_contains_20_to_50_complete_real_scenarios():
    scenarios = load_scenarios(Path(__file__).resolve().parents[1] / "evals" / "scenarios.json")

    assert 20 <= len(scenarios) <= 50
    assert {scenario["case_type"] for scenario in scenarios} == {"positive", "negative"}
    for scenario in scenarios:
        assert scenario["id"]
        assert scenario["task"]
        assert scenario["environment"]
        assert scenario["reference"]
        assert isinstance(scenario["required_behaviors"], list)
        assert isinstance(scenario["forbidden_behaviors"], list)
        assert scenario["rubric"]
        assert "transcript_review_notes" in scenario


def test_evaluator_scores_required_and_forbidden_behaviors():
    scenario = {
        "id": "repo-purpose",
        "task": "Explain a repository",
        "environment": "fixture",
        "reference": {"keywords": ["README", "skills"]},
        "case_type": "positive",
        "required_behaviors": ["goal_anchored", "action_started", "final_answer"],
        "forbidden_behaviors": ["unknown_tool_requested"],
        "rubric": {"behavior": 0.6, "answer": 0.4},
        "transcript_review_notes": "",
    }
    transcript = {
        "events": [{"type": "goal_anchored"}, {"type": "action_started"}, {"type": "final_answer"}],
        "final_answer": "Read the README; this is a reusable skills collection.",
    }

    result = evaluate_transcript(scenario, transcript)

    assert result["score"] == 1.0
    assert result["passed"] is True
    assert result["missing_required"] == []
    assert result["forbidden_seen"] == []


def test_failed_transcripts_are_written_for_human_review(tmp_path: Path):
    scenario = {
        "id": "failure-case",
        "task": "Recover from a failed tool",
        "environment": "fixture",
        "reference": {"keywords": ["confirmed"]},
        "case_type": "negative",
        "required_behaviors": ["recovery_started", "final_answer"],
        "forbidden_behaviors": ["unknown_tool_requested"],
        "rubric": {"behavior": 0.7, "answer": 0.3},
        "transcript_review_notes": "inspect recovery path",
    }
    transcript = {"events": [{"type": "unknown_tool_requested"}], "final_answer": ""}

    report = write_evaluation_report([(scenario, transcript)], tmp_path)
    saved = json.loads((tmp_path / "failures" / "failure-case.json").read_text(encoding="utf-8"))

    assert report["pass_rate"] == 0.0
    assert report["saturated"] is False
    assert saved["scenario"]["id"] == "failure-case"
    assert saved["transcript"] == transcript
