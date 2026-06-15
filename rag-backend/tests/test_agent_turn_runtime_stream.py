import json
from pathlib import Path

from app.agents.agent_turn_runtime import AgentTurnRuntime


class FakeGenerator:
    def __init__(self, answers: list[dict | str]) -> None:
        self.answers = answers
        self.system_prompts: list[str | None] = []

    def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
        self.system_prompts.append(system_prompt)
        if "Create hypothesis-driven decomposition" in prompt:
            if self.answers and isinstance(self.answers[0], dict) and "intent_anchor" in self.answers[0]:
                answer = self.answers.pop(0)
            else:
                answer = _planning_payload()
            return {
                "answer": json.dumps(answer, ensure_ascii=False),
                "tokens": {},
                "raw": {},
            }
        answer = self.answers.pop(0)
        return {
            "answer": json.dumps(answer, ensure_ascii=False) if isinstance(answer, dict) else answer,
            "tokens": {},
            "raw": {},
        }


class FakeWorkflow:
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        return {
            "id": "workflow_run",
            "mode": "real",
            "prompt": prompt,
            "status": "succeeded",
            "nodes": [{"id": "workflow_node", "status": "succeeded"}],
            "events": [],
            "toolCalls": [],
            "vectorMatches": [],
            "requestJson": {"prompt": prompt},
            "responseJson": {},
            "finalAnswer": "workflow answer",
            "latencyMs": 7,
        }


def _planning_payload() -> dict:
    return {
        "intent_anchor": {
            "user_goal": "See how the agent understands and executes the request.",
            "real_blocker": "The process is otherwise opaque.",
            "scope_direction": "execute",
            "needs_execution": True,
            "confidence": 0.8,
        },
        "task_decomposition": {
            "knowledge_gaps": ["What the user wants", "Which action should happen next"],
            "hypotheses": [{"id": "H1", "claim": "A ReAct step can advance the task.", "falsifiable_by": "No valid decision is returned."}],
            "verification_paths": [{"hypothesis_id": "H1", "path": "agent_turn_runtime stream"}],
            "dependency_graph": ["H1"],
            "ordered_tasks": [{"id": "T1", "description": "Run the next ReAct step.", "depends_on": [], "status": "pending"}],
        },
        "execution_mode": "execute",
        "next_action": "Continue with ReAct.",
    }


def test_agent_turn_runtime_streams_started_thinking_final_and_finished(tmp_path: Path) -> None:
    runtime = AgentTurnRuntime(
        generator=FakeGenerator([_planning_payload(), {"action": "final", "answer": "hello"}]),
        insurance_workflow=FakeWorkflow(),
        project_root=tmp_path,
        local_source_root=tmp_path,
    )

    events = list(
        runtime.stream(
            prompt="who are you?",
            collection="guides",
            agent_id="research-agent",
            thread_id="thread_1",
        )
    )

    assert [event["type"] for event in events] == [
        "run_started",
        "context_loaded",
        "intent_anchor",
        "task_decomposition",
        "react_decision",
        "final_answer",
        "run_finished",
    ]
    final_run = events[-1]["run"]
    assert final_run["finalAnswer"] == "hello"
    assert final_run["latencyMs"] > 0
    assert final_run["responseJson"]["streamEvents"][0]["type"] == "run_started"


def test_agent_turn_runtime_streams_tool_events(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("alpha marker in local file", encoding="utf-8")
    runtime = AgentTurnRuntime(
        generator=FakeGenerator(
            [
                _planning_payload(),
                {"action": "tool_call", "tool": "local_search", "arguments": {"query": "alpha marker"}},
                {"action": "final", "answer": "I found alpha marker in local file."},
            ]
        ),
        insurance_workflow=FakeWorkflow(),
        project_root=tmp_path,
        local_source_root=tmp_path,
    )

    events = list(
        runtime.stream(
            prompt="please search alpha marker in project files",
            collection="guides",
            agent_id="research-agent",
            thread_id="thread_1",
        )
    )

    event_types = [event["type"] for event in events]
    assert "tool_started" in event_types
    assert "tool_finished" in event_types
    assert "observation" in event_types
    assert events[-1]["run"]["toolCalls"][0]["name"] == "local_search"


def test_agent_turn_runtime_approved_command_uses_locked_command_without_model(tmp_path: Path) -> None:
    generator = FakeGenerator([{"action": "tool_call", "tool": "shell.exec", "arguments": {"command": "rm notes.md"}}])
    runtime = AgentTurnRuntime(
        generator=generator,
        insurance_workflow=FakeWorkflow(),
        project_root=tmp_path,
        local_source_root=tmp_path,
    )

    approval = runtime.run(
        prompt="rm notes.md",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        collected_vars={"commandMode": "build"},
    )["approvalRequest"]

    result = runtime.run(
        prompt="rm notes.md",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        collected_vars={
            "approvalId": approval["id"],
            "approvedCommand": approval["command"],
            "commandApproved": True,
            "commandMode": approval["mode"],
        },
    )

    assert result["status"] == "succeeded"
    assert result["toolCalls"][0]["arguments"]["command"] == "rm notes.md"
    assert len(generator.system_prompts) == 2


def test_agent_turn_runtime_rejects_mismatched_approval_id(tmp_path: Path) -> None:
    runtime = AgentTurnRuntime(
        generator=FakeGenerator([{"action": "final", "answer": "should not be used"}]),
        insurance_workflow=FakeWorkflow(),
        project_root=tmp_path,
        local_source_root=tmp_path,
    )

    result = runtime.run(
        prompt="rm notes.md",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        collected_vars={
            "approvalId": "cmd:not-the-right-id",
            "approvedCommand": "rm notes.md",
            "commandApproved": True,
            "commandMode": "build",
        },
    )

    assert result["status"] == "failed"
    assert "approval_mismatch" in result["finalAnswer"]


def test_agent_turn_runtime_asks_before_external_downloads_write(tmp_path: Path) -> None:
    downloads = tmp_path.parent / "Downloads" / "note.txt"
    command = f'echo hello > "{downloads}"'
    runtime = AgentTurnRuntime(
        generator=FakeGenerator([{"action": "tool_call", "tool": "shell.exec", "arguments": {"command": command}}]),
        insurance_workflow=FakeWorkflow(),
        project_root=tmp_path,
        local_source_root=tmp_path,
    )

    result = runtime.run(
        prompt="create note in Downloads",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        collected_vars={"commandMode": "build"},
    )

    assert result["status"] == "awaiting_approval"
    assert result["approvalRequest"]["risk"] == "external_path"
