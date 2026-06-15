import json
from pathlib import Path


class FakeLLM:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[dict] = []

    def generate(self, prompt: str, system_prompt: str | None = None, tools: list[dict] | None = None, tool_choice: str | dict | None = None) -> dict:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        return self.responses.pop(0)


def _planning_payload(execution_mode: str = "plan_only") -> dict:
    return {
        "intent_anchor": {
            "user_goal": "Understand how the project handles agent process visibility.",
            "real_blocker": "The current flow hides intent, decomposition, and tool actions.",
            "scope_direction": "inspect and plan",
            "constraints": ["do not force insurance workflow"],
            "needs_execution": execution_mode == "execute",
            "confidence": 0.84,
        },
        "task_decomposition": {
            "knowledge_gaps": ["Where context is assembled", "How tools are exposed"],
            "hypotheses": [
                {
                    "id": "H1",
                    "claim": "The runtime can expose planning before tool execution.",
                    "falsifiable_by": "No planning events are emitted before final answer.",
                }
            ],
            "verification_paths": [{"hypothesis_id": "H1", "path": "app/agents/transparent_runtime.py"}],
            "dependency_graph": ["H1"],
            "ordered_tasks": [{"id": "T1", "description": "Inspect runtime", "depends_on": [], "status": "pending"}],
        },
        "execution_mode": execution_mode,
        "next_action": "emit public planning events",
    }


def test_transparent_runtime_streams_context_intent_and_decomposition_without_fixed_routes(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM([{"answer": json.dumps(_planning_payload("plan_only"), ensure_ascii=False)}])
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1])

    events = list(runtime.stream("show me how this works", thread_id="thread-1", user_id="user-1"))

    assert [event["type"] for event in events] == [
        "run_started",
        "context_loaded",
        "intent_anchor",
        "task_decomposition",
        "final_answer",
        "run_finished",
    ]
    assert events[2]["intent"]["real_blocker"] == "The current flow hides intent, decomposition, and tool actions."
    assert "official_evidence_research" not in llm.calls[0]["system_prompt"]
    assert "identity" not in llm.calls[0]["system_prompt"]
    assert "clarification" not in llm.calls[0]["system_prompt"]


def test_transparent_runtime_executes_tool_call_as_observation_then_continues(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    source = tmp_path / "notes.md"
    source.write_text("alpha marker is here", encoding="utf-8")
    llm = FakeLLM(
        [
            {"answer": json.dumps(_planning_payload("execute"), ensure_ascii=False)},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "local_search",
                            "arguments": json.dumps({"query": "alpha marker", "root": str(tmp_path)}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"answer": "I found alpha marker in notes.md."},
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=3)

    events = list(runtime.stream("find alpha marker", thread_id="thread-1", user_id="user-1"))
    event_types = [event["type"] for event in events]

    assert "tool_started" in event_types
    assert "tool_finished" in event_types
    assert "observation" in event_types
    assert events[-2]["finalAnswer"] == "I found alpha marker in notes.md."
    assert "alpha marker is here" in json.dumps(llm.calls[-1], ensure_ascii=False)
