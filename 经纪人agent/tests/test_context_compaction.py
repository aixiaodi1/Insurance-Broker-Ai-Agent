from unittest.mock import MagicMock

from app.agents.compact import compactor as compact_mod
from app.agents.compact.engine import ContextEngine
from app.agents.compact import ContextCompressor
from app.agents.compact.prompts import (
    format_compact_summary,
    get_compact_prompt,
    get_iterative_compact_prompt,
)
from app.agents.compact.token_counter import (
    estimate_message_tokens,
    estimate_tokens,
    estimate_tool_event_tokens,
    format_tool_events_for_summary,
)
from app.agents.nodes.context_nodes import compact_context as context_node_compact


def _compressor():
    return compact_mod.get_compressor()


def setup_function():
    compact_mod.reset_compact_failures()


def test_fallback_truncation_keeps_recent_messages():
    state = {
        "messages": [{"role": "user", "content": f"消息{i}"} for i in range(25)],
        "tool_events": [
            {"tool": "http_get", "status": "success", "url": f"https://example.com/{i}"}
            for i in range(60)
        ],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5, "max_tool_events": 3},
    }
    new_state = compact_mod.compact_context(state)
    assert len(new_state["messages"]) == 5
    assert "消息0" in new_state["conversation_summary"]
    assert len(new_state["tool_events"]) == 3
    assert "tool_events_summary" in new_state


def test_no_compaction_when_under_threshold():
    state = {
        "messages": [{"role": "user", "content": "hello"} for _ in range(3)],
        "tool_events": [{"tool": "search", "status": "success"} for _ in range(3)],
        "conversation_summary": None,
        "context_budget": {"max_messages": 10, "max_tool_events": 10},
    }
    new_state = compact_mod.compact_context(state)
    assert len(new_state["messages"]) == 3
    assert new_state["conversation_summary"] is None
    assert len(new_state["tool_events"]) == 3


def test_tool_events_rollup_has_counts():
    fail_events = [{"tool": "web_search", "node": "intake", "status": "fail", "error": "timeout"} for _ in range(5)]
    success_events = [{"tool": "web_fetch", "node": "evidence", "status": "success"} for _ in range(30)]
    events = fail_events + success_events
    state = {
        "messages": [{"role": "user", "content": "test"}],
        "tool_events": events,
        "conversation_summary": None,
        "context_budget": {"max_tool_events": 5},
    }
    new_state = compact_mod.compact_context(state)
    assert len(new_state["tool_events"]) == 5
    rollup = new_state["tool_events_summary"]
    assert rollup["total"] == 35
    assert rollup["success"] == 30
    assert rollup["fail"] == 5
    assert rollup["tool_counts"]["web_fetch"] >= 25
    assert len(rollup["fail_details"]) > 0


def test_existing_summary_appended_in_fallback():
    state = {
        "messages": [{"role": "user", "content": f"msg{i}"} for i in range(15)],
        "tool_events": [],
        "conversation_summary": "之前摘要",
        "context_budget": {"max_messages": 5, "max_tool_events": 20},
    }
    new_state = compact_mod.compact_context(state)
    assert "之前摘要" in new_state["conversation_summary"]
    assert "msg0" in new_state["conversation_summary"]


def test_context_node_wrapper():
    state = {
        "messages": [{"role": "user", "content": f"n{i}"} for i in range(12)],
        "tool_events": [],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5},
    }
    new_state = context_node_compact(state)
    assert len(new_state["messages"]) == 5


def test_compact_with_llm_success():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = {
        "answer": "<analysis>thought</analysis>\n<summary>\n1. 用户请求和意图：\n   测试请求\n</summary>"
    }
    state = {
        "messages": [{"role": "user", "content": f"msg{i}"} for i in range(15)],
        "tool_events": [],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5},
    }
    new_state = compact_mod.compact_context(state, llm_client=mock_llm)
    assert len(new_state["messages"]) == 5
    assert "测试请求" in new_state["conversation_summary"]
    assert new_state["conversation_summary"].startswith("对话摘要：")
    mock_llm.generate.assert_called_once()
    call_kwargs = mock_llm.generate.call_args[1]
    assert "system_prompt" in call_kwargs
    assert "prompt" in call_kwargs


def test_compact_llm_failure_falls_back_to_truncation():
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("API error")
    state = {
        "messages": [{"role": "user", "content": f"msg{i}"} for i in range(15)],
        "tool_events": [],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5},
    }
    new_state = compact_mod.compact_context(state, llm_client=mock_llm)
    assert len(new_state["messages"]) == 5
    assert "msg0" in new_state["conversation_summary"]


def test_circuit_breaker_stops_llm_after_consecutive_failures():
    compact_mod.reset_compact_failures()
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("API error")
    compressor = _compressor()

    for i in range(compressor.max_consecutive_failures + 1):
        state = {
            "messages": [{"role": "user", "content": f"msg{j}"} for j in range(15)],
            "tool_events": [],
            "conversation_summary": f"summary_{i}",
            "context_budget": {"max_messages": 5},
        }
        new_state = compact_mod.compact_context(state, llm_client=mock_llm)
        assert len(new_state["messages"]) == 5

    assert compressor._consecutive_failures >= compressor.max_consecutive_failures


def test_circuit_breaker_trips_and_stays_tripped():
    compact_mod.reset_compact_failures()
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("fail")
    compressor = _compressor()

    for i in range(compressor.max_consecutive_failures):
        state = {
            "messages": [{"role": "user", "content": f"msg{j}"} for j in range(15)],
            "tool_events": [],
            "conversation_summary": f"s{i}",
            "context_budget": {"max_messages": 5},
        }
        compact_mod.compact_context(state, llm_client=mock_llm)

    assert compressor._consecutive_failures == compressor.max_consecutive_failures

    mock_llm.generate.side_effect = None
    mock_llm.generate.return_value = {
        "answer": "<analysis>ok</analysis>\n<summary>\n1. summary text\n   recovered content\n</summary>"
    }
    state = {
        "messages": [{"role": "user", "content": f"msg{j}"} for j in range(15)],
        "tool_events": [],
        "conversation_summary": "prev",
        "context_budget": {"max_messages": 5},
    }
    new_state = compact_mod.compact_context(state, llm_client=mock_llm)

    assert compressor._consecutive_failures == compressor.max_consecutive_failures


def test_compact_prompt_has_required_sections():
    prompt = get_compact_prompt()
    assert "<analysis>" in prompt
    assert "<summary>" in prompt
    assert "用户请求和意图" in prompt
    assert "涉及产品" in prompt
    assert "关键发现" in prompt


def test_compact_prompt_with_custom_instructions():
    prompt = get_compact_prompt(custom_instructions="重点记录错误信息")
    assert "重点记录错误信息" in prompt


def test_iterative_compact_prompt_has_merge_instruction():
    prompt = get_iterative_compact_prompt()
    assert "已有的对话摘要" in prompt or "合并" in prompt


def test_format_compact_summary_strips_analysis():
    raw = "<analysis>internal thoughts</analysis>\n<summary>\n1. 关键发现：\n   test\n</summary>"
    formatted = format_compact_summary(raw)
    assert "internal thoughts" not in formatted
    assert "test" in formatted
    assert "对话摘要：" in formatted
    assert formatted.startswith("对话摘要：")


def test_format_compact_summary_no_tags():
    raw = "plain text response"
    formatted = format_compact_summary(raw)
    assert formatted == "plain text response"


def test_token_counter_estimate():
    zh = estimate_tokens("保险产品研究")
    en = estimate_tokens("insurance product research")
    assert zh > 0
    assert en > 0
    assert estimate_tokens("") == 1


def test_estimate_message_tokens():
    msgs = [{"role": "user", "content": "查询众民保的赔付条款"} for _ in range(5)]
    total = estimate_message_tokens(msgs)
    assert total > 0


def test_estimate_tool_event_tokens():
    events = [
        {"tool": "web_fetch", "input_summary": {"url": "https://example.com"}, "output_summary": {"text": "条款内容"}}
    ]
    total = estimate_tool_event_tokens(events)
    assert total > 0


def test_format_tool_events_for_summary():
    events = [
        {"node": "evidence", "tool": "web_fetch", "status": "success", "input_summary": {"url": "http://x.com"}, "output_summary": {"text": "hello"}}
    ]
    text = format_tool_events_for_summary(events)
    assert "evidence" in text
    assert "web_fetch" in text
    assert "success" in text


def test_no_tool_events_rollup_when_under_threshold():
    state = {
        "messages": [{"role": "user", "content": "test"}],
        "tool_events": [{"tool": "search", "status": "success"} for _ in range(3)],
        "conversation_summary": None,
        "context_budget": {"max_tool_events": 10},
    }
    new_state = compact_mod.compact_context(state)
    assert "tool_events_summary" not in new_state
    assert len(new_state["tool_events"]) == 3


def test_llm_empty_response_falls_back():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = {"answer": ""}
    state = {
        "messages": [{"role": "user", "content": f"msg{i}"} for i in range(15)],
        "tool_events": [],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5},
    }
    new_state = compact_mod.compact_context(state, llm_client=mock_llm)
    assert len(new_state["messages"]) == 5
    assert new_state["conversation_summary"] is not None


def test_compact_preserves_messages_when_under_budget():
    state = {
        "messages": [{"role": "user", "content": "仅一条消息"}],
        "tool_events": [],
        "conversation_summary": "已有摘要",
        "context_budget": {"max_messages": 12, "max_tool_events": 20},
    }
    new_state = compact_mod.compact_context(state)
    assert len(new_state["messages"]) == 1
    assert new_state["conversation_summary"] == "已有摘要"


def test_anti_thrashing_skips_llm_after_repeated_ineffective():
    compact_mod.reset_compact_failures()
    mock_llm = MagicMock()
    mock_llm.generate.return_value = {
        "answer": "<analysis>ok</analysis>\n<summary>\n1. 用户请求和意图：\n   测试请求\n</summary>"
    }
    compressor = _compressor()
    compressor._ineffective_count = compressor.max_ineffective_count

    state = {
        "messages": [{"role": "user", "content": f"msg{i}"} for i in range(15)],
        "tool_events": [],
        "conversation_summary": None,
        "context_budget": {"max_messages": 5},
    }
    new_state = compact_mod.compact_context(state, llm_client=mock_llm)

    assert "对话摘要：" not in new_state.get("conversation_summary", "")
    mock_llm.generate.assert_not_called()


def test_context_engine_abc():
    assert issubclass(ContextCompressor, ContextEngine)
    instance = ContextCompressor()
    assert instance.name == "hermes_compressor"
    assert hasattr(instance, "should_compress")
    assert hasattr(instance, "compress")
    assert hasattr(instance, "update_from_response")
    assert hasattr(instance, "on_session_reset")


def test_iterative_prompt_used_when_summary_exists():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = {
        "answer": "<analysis>merge</analysis>\n<summary>\n1. 用户请求和意图：\n   合并后的摘要\n</summary>"
    }
    state = {
        "messages": [{"role": "user", "content": f"msg{i}"} for i in range(15)],
        "tool_events": [],
        "conversation_summary": "已有摘要内容",
        "context_budget": {"max_messages": 5},
    }
    new_state = compact_mod.compact_context(state, llm_client=mock_llm)
    assert len(new_state["messages"]) == 5
    assert "合并后的摘要" in new_state["conversation_summary"]
    call_args = mock_llm.generate.call_args[1]
    system = call_args["system_prompt"]
    assert "已有的对话摘要" in system or "合并" in system


def test_max_consecutive_failures_accessible():
    assert compact_mod.MAX_CONSECUTIVE_FAILURES >= 1
