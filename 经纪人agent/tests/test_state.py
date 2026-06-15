from app.agents.state import new_agent_state


def test_new_agent_state_sets_required_defaults():
    state = new_agent_state(
        user_id="user-1",
        user_input="帮我查众民保",
        thread_id="user-1:task-1",
    )
    assert state["user_id"] == "user-1"
    assert state["thread_id"] == "user-1:task-1"
    assert state["user_input"] == "帮我查众民保"
    assert state["user_level"] == "novice"
    assert state["local_candidates"] == []
    assert state["tool_events"] == []
