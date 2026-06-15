def test_global_router_uses_local_clue_to_enter_research_for_unknown_product(tmp_path, monkeypatch):
    from app.agents.routing import route_user_intent
    from app.config import settings

    source = tmp_path / "mysterycare.md"
    source.write_text(
        "MysteryCare insurance product official terms and coverage notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "local_source_root", tmp_path)

    state = {
        "user_input": "please look up MysteryCare",
        "tool_events": [],
    }

    result = route_user_intent(state)

    assert result["task_type"] == "official_evidence_research"
    assert result["route_reason"] == "global_router_local_insurance_clue"
    assert any(
        event["node"] == "global_router" and event["tool"] == "local_search"
        for event in result["tool_events"]
    )


def test_global_router_probes_chinese_look_request(tmp_path, monkeypatch):
    from app.agents.routing import route_user_intent
    from app.config import settings

    source = tmp_path / "mysterycare.md"
    source.write_text(
        "MysteryCare insurance product official terms and coverage notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "local_source_root", tmp_path)

    result = route_user_intent(
        {
            "user_input": "\u5e2e\u6211\u770b\u770b MysteryCare",
            "tool_events": [],
        }
    )

    assert result["task_type"] == "official_evidence_research"
    assert result["route_reason"] == "global_router_local_insurance_clue"


def test_global_router_can_use_model_tool_call_for_triage(tmp_path, monkeypatch):
    from app.agents.routing import route_user_intent
    from app.config import settings

    source = tmp_path / "mysterycare.md"
    source.write_text(
        "MysteryCare insurance product official terms and coverage notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "local_source_root", tmp_path)

    class FakeRouterModel:
        def __init__(self):
            self.tools = None

        def generate(self, prompt, system_prompt=None, tools=None, tool_choice=None):
            self.tools = tools
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "local_search",
                            "arguments": '{"query":"MysteryCare","limit":3}',
                        }
                    }
                ]
            }

    router_model = FakeRouterModel()
    result = route_user_intent(
        {"user_input": "please investigate MysteryCare", "tool_events": []},
        router_model=router_model,
    )

    assert result["task_type"] == "official_evidence_research"
    assert result["route_reason"] == "global_router_model_tool_clue"
    assert {tool["function"]["name"] for tool in router_model.tools} == {
        "local_search",
        "resolve_product_alias",
    }


def test_global_router_does_not_probe_clear_identity_question(tmp_path, monkeypatch):
    from app.agents.routing import route_user_intent
    from app.config import settings

    monkeypatch.setattr(settings, "local_source_root", tmp_path)
    state = {
        "user_input": "who are you",
        "tool_events": [],
    }

    result = route_user_intent(state)

    assert result["task_type"] == "identity"
    assert result["tool_events"] == []
