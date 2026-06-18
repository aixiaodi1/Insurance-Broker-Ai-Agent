import json
from pathlib import Path

from app.memory.schemas import ToolResult


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

    events = list(runtime.stream("plan only: show me how this works", thread_id="thread-1", user_id="user-1"))

    assert [event["type"] for event in events] == [
        "run_started",
        "goal_anchored",
        "plan_updated",
        "final_answer",
        "run_finished",
    ]
    assert events[1]["goal"]["goal"] == "Understand how the project handles agent process visibility."
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
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {
                            "name": "local_read",
                            "arguments": json.dumps({"path": str(source)}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"answer": "I found alpha marker in notes.md."},
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=4)

    events = list(runtime.stream("find alpha marker", thread_id="thread-1", user_id="user-1"))
    event_types = [event["type"] for event in events]

    assert "action_started" in event_types
    assert "action_completed" in event_types
    assert events[-2]["finalAnswer"] == "I found alpha marker in notes.md."
    assert "alpha marker is here" in json.dumps(llm.calls[-1], ensure_ascii=False)


def test_transparent_runtime_reports_unknown_tool_and_continues(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM(
        [
            {"answer": json.dumps(_planning_payload("execute"), ensure_ascii=False)},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-unknown",
                        "type": "function",
                        "function": {
                            "name": "github.repo_tree",
                            "arguments": json.dumps({"repo": "openclaw/openclaw"}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"answer": "我无法调用 github.repo_tree；当前需要改用可用工具继续确认。"},
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=2)

    events = list(runtime.stream("看看 openclaw 默认工具", thread_id="thread-1", user_id="user-1"))
    unknown_events = [
        event
        for event in events
        if event.get("type") == "recovery_started" and event.get("recovery", {}).get("kind") == "unknown_tool_requested"
    ]

    assert unknown_events
    assert unknown_events[0]["recovery"]["tool"] == "github.repo_tree"
    assert "local_search" in unknown_events[0]["recovery"]["available_tools"]
    assert "github.repo_tree" in llm.calls[-1]["prompt"]
    assert "local_search" in llm.calls[-1]["prompt"]
    assert events[-2]["type"] == "final_answer"


def test_transparent_runtime_routes_github_resource_to_available_web_tools(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM(
        [
            {"answer": json.dumps(_planning_payload("execute"), ensure_ascii=False)},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-unknown",
                        "type": "function",
                        "function": {
                            "name": "github.repo_tree",
                            "arguments": json.dumps({"repo": "JimLiu/baoyu-skills"}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"answer": "我会改用 web_fetch 获取官方仓库信息。"},
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=2)

    events = list(runtime.stream("github.com/JimLiu/baoyu-skills 你帮我看看这个项目有什么用", thread_id="thread-1", user_id="user-1"))
    unknown_events = [
        event
        for event in events
        if event.get("type") == "recovery_started" and event.get("recovery", {}).get("kind") == "unknown_tool_requested"
    ]

    assert {tool["function"]["name"] for tool in llm.calls[1]["tools"]} == {"web_fetch", "web_search"}
    assert unknown_events[0]["recovery"]["data"]["recovery_tools"] == ["web_fetch", "web_search"]
    assert "https://api.github.com/repos/JimLiu/baoyu-skills" in llm.calls[-1]["prompt"]
    assert "web_fetch" in llm.calls[-1]["prompt"]


def test_transparent_runtime_blocks_local_tool_when_remote_resource_is_routed(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM(
        [
            {"answer": json.dumps(_planning_payload("execute"), ensure_ascii=False)},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-local",
                        "type": "function",
                        "function": {
                            "name": "local_search",
                            "arguments": json.dumps({"query": "JimLiu/baoyu-skills"}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"answer": "远程仓库问题应改用 web_fetch 或 web_search。"},
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=2)

    events = list(runtime.stream("github.com/JimLiu/baoyu-skills 你帮我看看这个项目有什么用", thread_id="thread-1", user_id="user-1"))
    blocked_events = [
        event
        for event in events
        if event.get("type") == "recovery_started" and event.get("recovery", {}).get("kind") == "tool_not_available_for_resource"
    ]

    assert blocked_events
    assert blocked_events[0]["recovery"]["tool"] == "local_search"
    assert blocked_events[0]["recovery"]["data"]["recovery_tools"] == ["web_fetch", "web_search"]
    assert any(event.get("toolCall", {}).get("failureCategory") == "tool_not_available_for_resource" for event in events)


def test_transparent_runtime_feeds_tool_failure_into_next_react_turn(monkeypatch, tmp_path: Path):
    import app.agents.transparent_runtime as transparent_runtime

    from app.agents.transparent_runtime import TransparentAgentRuntime

    def fake_execute_tool(tool_name: str, arguments: dict) -> ToolResult:
        return ToolResult(ok=False, source=tool_name, data={"url": arguments.get("url")}, error="HTTPError")

    monkeypatch.setattr(transparent_runtime, "execute_tool", fake_execute_tool)
    llm = FakeLLM(
        [
            {"answer": json.dumps(_planning_payload("execute"), ensure_ascii=False)},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-fetch",
                        "type": "function",
                        "function": {
                            "name": "web_fetch",
                            "arguments": json.dumps({"url": "https://example.invalid"}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {"answer": "web_fetch 失败后我会换搜索或其他来源继续确认。"},
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=2)

    events = list(runtime.stream("查一个网页", thread_id="thread-1", user_id="user-1"))

    assert "HTTPError" in llm.calls[-1]["prompt"]
    assert "revise" in llm.calls[-1]["prompt"].lower()
    assert any(event.get("toolCall", {}).get("status") == "failed" for event in events)
    assert "未确认" in events[-2]["finalAnswer"] or "无法确认" in events[-2]["finalAnswer"]


def test_transparent_runtime_system_prompt_exposes_public_tool_failures(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM([{"answer": json.dumps(_planning_payload("plan_only"), ensure_ascii=False)}])
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1])
    prompt = runtime._react_system_prompt(runtime.context_assembler.build())

    assert "tool failures" in prompt.lower()
    assert "GitHub API responses" not in prompt
    assert "Never expose internal error details" not in prompt
    assert "secret" in prompt.lower()


def test_transparent_runtime_max_turns_fallback_marks_unconfirmed(monkeypatch, tmp_path: Path):
    import app.agents.transparent_runtime as transparent_runtime

    from app.agents.transparent_runtime import TransparentAgentRuntime

    monkeypatch.setattr(
        transparent_runtime,
        "execute_tool",
        lambda tool_name, arguments: ToolResult(ok=False, source=tool_name, data={}, error="HTTPError"),
    )
    llm = FakeLLM(
        [
            {"answer": json.dumps(_planning_payload("execute"), ensure_ascii=False)},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-fetch",
                        "type": "function",
                        "function": {"name": "web_fetch", "arguments": json.dumps({"url": "https://example.invalid"})},
                    }
                ],
            },
        ]
    )
    runtime = TransparentAgentRuntime(llm_client=llm, project_root=Path(__file__).resolve().parents[1], max_turns=1)

    events = list(runtime.stream("查一个网页", thread_id="thread-1", user_id="user-1"))

    assert events[-2]["type"] == "final_answer"
    assert "未确认" in events[-2]["finalAnswer"] or "无法确认" in events[-2]["finalAnswer"]


def test_required_web_search_blocks_early_answer_and_emits_public_search_trace(monkeypatch):
    import app.agents.transparent_runtime as transparent_runtime

    planning = _planning_payload("execute")
    planning["web_search_requirement"] = {
        "mode": "required",
        "freshness": "recent",
        "risk_level": "high",
        "summary": "需要核验最新官方信息",
    }
    calls = []

    def fake_execute(tool_name, arguments):
        calls.append((tool_name, arguments))
        if tool_name == "web_fetch":
            return ToolResult(
                ok=True,
                source=tool_name,
                data={
                    "url": arguments["url"],
                    "text": "已读取官方正文",
                    "content_kind": "webpage_text",
                    "untrusted_external_content": True,
                    "risk_flags": [],
                },
            )
        return ToolResult(
            ok=True,
            source=tool_name,
            data={
                "results": [{"url": "https://example.com/source"}],
                "public_trace": [
                    {"type": "query_plan_ready", "query_count": 2, "roles": ["official", "document"]},
                    {"type": "provider_search_finished", "provider": "baidu_qianfan", "ok": True, "result_count": 1},
                ],
            },
        )

    monkeypatch.setattr(transparent_runtime, "execute_tool", fake_execute)
    llm = FakeLLM(
        [
            {"answer": json.dumps(planning, ensure_ascii=False)},
            {"answer": "我直接凭记忆回答。"},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-search",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": json.dumps({"query": "最新官方信息"})},
                    }
                ],
            },
            {"answer": "我先基于搜索摘要回答。"},
            {
                "answer": "",
                "tool_calls": [
                    {
                        "id": "call-fetch",
                        "type": "function",
                        "function": {"name": "web_fetch", "arguments": json.dumps({"url": "https://example.com/source"})},
                    }
                ],
            },
            {"answer": "根据已读取来源回答。"},
            {"answer": "根据已读取来源回答。[来源](https://example.com/source)"},
        ]
    )
    runtime = transparent_runtime.TransparentAgentRuntime(
        llm_client=llm,
        project_root=Path(__file__).resolve().parents[1],
        max_turns=6,
    )

    events = list(runtime.stream("最近有什么官方变化？"))

    assert calls and calls[0][0] == "web_search"
    assert any(event["type"] == "recovery_started" for event in events)
    assert sum(event["type"] == "action_started" for event in events) == 2
    assert sum(event["type"] == "action_completed" for event in events) == 2
    assert events[-2]["finalAnswer"] == "根据已读取来源回答。[来源](https://example.com/source)"
