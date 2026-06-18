import json
from pathlib import Path

from app.agents.run_control import RunControlStore
from app.memory.schemas import ToolResult


class FakeLLM:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[dict] = []

    def generate(self, prompt: str, system_prompt=None, tools=None, tool_choice=None) -> dict:
        self.calls.append({"prompt": prompt, "tools": tools})
        return self.responses.pop(0)


def planning(goal: str = "Inspect the repository", execute: bool = True) -> dict:
    return {
        "intent_anchor": {
            "user_goal": goal,
            "real_blocker": "Repository content has not been read",
            "scope_direction": "inspect",
            "constraints": [],
            "needs_execution": execute,
            "confidence": 0.9,
        },
        "task_decomposition": {
            "knowledge_gaps": ["README content"],
            "hypotheses": [],
            "verification_paths": [],
            "dependency_graph": [],
            "ordered_tasks": [{"id": "T1", "description": "Read README", "depends_on": [], "status": "pending"}],
        },
        "execution_mode": "execute" if execute else "plan_only",
        "next_action": "read source",
    }


def test_runtime_emits_goal_plan_and_action_events(monkeypatch, tmp_path: Path):
    import app.agents.transparent_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "execute_tool",
        lambda name, args: ToolResult(ok=True, source=name, data={"text": "README body", "url": args.get("url", "")}),
    )
    llm = FakeLLM(
        [
            {"answer": json.dumps(planning(), ensure_ascii=False)},
            {"answer": "", "tool_calls": [{"function": {"name": "web_fetch", "arguments": json.dumps({"url": "https://example.com"})}}]},
            {"answer": "The repository contains reusable skills. https://example.com"},
        ]
    )
    runtime = runtime_module.TransparentAgentRuntime(llm, tmp_path, max_turns=3)

    events = list(runtime.stream("https://example.com inspect this project", thread_id="thread-1", user_id="user-1"))
    types = [event["type"] for event in events]

    assert "goal_anchored" in types
    assert "plan_updated" in types
    assert "action_started" in types
    assert "action_completed" in types
    assert "final_answer" in types
    assert "tool_started" not in types


def test_runtime_does_not_accept_a_promise_to_recover_as_completion(monkeypatch, tmp_path: Path):
    import app.agents.transparent_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "execute_tool",
        lambda name, args: ToolResult(ok=True, source=name, data={"text": "official README", "url": args.get("url", "")}),
    )
    llm = FakeLLM(
        [
            {"answer": json.dumps(planning(), ensure_ascii=False)},
            {"answer": "", "tool_calls": [{"function": {"name": "github.repo_tree", "arguments": "{}"}}]},
            {"answer": "我会改用 web_fetch 继续确认。"},
            {"answer": "", "tool_calls": [{"function": {"name": "web_fetch", "arguments": json.dumps({"url": "https://github.com/acme/repo"})}}]},
            {"answer": "已确认项目用途。https://github.com/acme/repo"},
        ]
    )
    runtime = runtime_module.TransparentAgentRuntime(llm, tmp_path, max_turns=5)

    events = list(runtime.stream("github.com/acme/repo 有什么用", thread_id="thread-1", user_id="user-1"))

    assert events[-2]["finalAnswer"].startswith("已确认")
    assert any(event["type"] == "recovery_started" for event in events)
    assert not any(event.get("finalAnswer") == "我会改用 web_fetch 继续确认。" for event in events)


def test_runtime_stops_at_a_safe_point_and_preserves_state(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    llm = FakeLLM([])
    runtime = TransparentAgentRuntime(llm, tmp_path, control_store=store)
    stream = runtime.stream("inspect project", thread_id="thread-1", user_id="user-1")

    started = next(stream)
    store.request_interrupt(started["run_id"])
    remaining = list(stream)

    assert [event["type"] for event in remaining][-3:] == ["interrupt_requested", "run_interrupted", "run_finished"]
    assert remaining[-1]["run"]["status"] == "interrupted"
    assert store.get_run(started["run_id"])["status"] == "interrupted"
    assert llm.calls == []


def test_runtime_applies_queued_guidance_before_planning(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    llm = FakeLLM(
        [
            {"answer": json.dumps(planning("Analyze the ReAct loop", execute=False), ensure_ascii=False)},
            {"answer": "已根据补充分析 ReAct loop。"},
        ]
    )
    runtime = TransparentAgentRuntime(llm, tmp_path, control_store=store)
    stream = runtime.stream("inspect the query answer", thread_id="thread-1", user_id="user-1")

    started = next(stream)
    store.upsert_guidance(started["run_id"], "重点分析 ReAct loop", priority="immediate")
    remaining = list(stream)

    assert any(event["type"] == "guidance_applied" for event in remaining)
    assert any(event["type"] == "plan_updated" for event in remaining)
    assert "重点分析 ReAct loop" in llm.calls[0]["prompt"]
    assert store.get_pending_guidance(started["run_id"]) is None


def test_next_run_on_same_thread_reuses_interrupted_public_state(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    store.start_run("run-old", thread_id="thread-1", user_id="user-1", state={})
    store.finish_run(
        "run-old",
        status="interrupted",
        state={"planning": {"goal": "inspect repo"}, "observations": [{"tool": "web_fetch", "ok": True}]},
    )
    llm = FakeLLM(
        [
            {"answer": json.dumps(planning(execute=False), ensure_ascii=False)},
            {"answer": "已结合上一轮结果继续。"},
        ]
    )
    runtime = TransparentAgentRuntime(llm, tmp_path, control_store=store)

    list(runtime.stream("继续", thread_id="thread-1", user_id="user-1"))

    assert "previous_run_state" in llm.calls[0]["prompt"]
    assert "web_fetch" in llm.calls[0]["prompt"]


def test_next_run_applies_guidance_left_pending_after_previous_run_finished(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    store = RunControlStore(tmp_path / "runs.sqlite3")
    store.init_schema()
    store.start_run("run-old", thread_id="thread-1", user_id="user-1", state={})
    store.upsert_guidance("run-old", "focus on the ReAct loop", priority="normal")
    store.finish_run("run-old", status="succeeded", state={"planning": {}, "observations": []})
    llm = FakeLLM(
        [
            {"answer": json.dumps(planning("Analyze ReAct", execute=False), ensure_ascii=False)},
            {"answer": "The guidance was applied."},
        ]
    )
    runtime = TransparentAgentRuntime(llm, tmp_path, control_store=store)

    events = list(runtime.stream("continue", thread_id="thread-1", user_id="user-1"))

    assert any(event["type"] == "guidance_applied" for event in events)
    assert "focus on the ReAct loop" in llm.calls[0]["prompt"]
    assert store.get_pending_guidance("run-old") is None


def test_non_execution_plan_still_answers_unless_user_explicitly_requests_plan_only(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM(
        [
            {"answer": json.dumps(planning("Reply to the greeting", execute=False), ensure_ascii=False)},
            {"answer": "你好！"},
        ]
    )
    runtime = TransparentAgentRuntime(llm, tmp_path, max_turns=1)

    events = list(runtime.stream("你好", thread_id="thread-1", user_id="user-1"))

    assert events[-2]["finalAnswer"] == "你好！"


def test_simple_chat_can_finish_when_planner_overstates_execution_need(tmp_path: Path):
    from app.agents.transparent_runtime import TransparentAgentRuntime

    llm = FakeLLM(
        [
            {"answer": json.dumps(planning("Reply briefly", execute=True), ensure_ascii=False)},
            {"answer": "Hello!"},
        ]
    )
    runtime = TransparentAgentRuntime(llm, tmp_path, max_turns=2)

    events = list(runtime.stream("Say hello briefly.", thread_id="thread-1", user_id="user-1"))

    assert events[-2]["finalAnswer"] == "Hello!"
