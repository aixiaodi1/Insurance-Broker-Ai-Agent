import json
from pathlib import Path

from app.agents.research_graph import ResearchAgentGraph
from app.services.conversation_memory import ConversationMemoryStore


class FakeRagQueryService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        self.calls.append(
            {
                "prompt": prompt,
                "collection": collection,
                "agent_id": agent_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "collected_vars": collected_vars,
            }
        )
        return {
            "id": "run_fake",
            "mode": "real",
            "prompt": prompt,
            "status": "succeeded",
            "nodes": [{"id": "receive_input", "status": "succeeded"}],
            "events": [{"id": "evt_receive_input", "nodeId": "receive_input"}],
            "toolCalls": [],
            "vectorMatches": [],
            "requestJson": {"prompt": prompt},
            "responseJson": {"collection": collection},
            "finalAnswer": "ok",
        }


class EmptyRagQueryService(FakeRagQueryService):
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        self.calls.append(
            {
                "prompt": prompt,
                "collection": collection,
                "agent_id": agent_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "collected_vars": collected_vars,
            }
        )
        return {
            "id": "run_empty",
            "mode": "real",
            "prompt": prompt,
            "status": "succeeded",
            "nodes": [{"id": "retrieve_context", "status": "succeeded"}],
            "events": [{"id": "evt_retrieve_context", "nodeId": "retrieve_context"}],
            "toolCalls": [],
            "vectorMatches": [],
            "requestJson": {"prompt": prompt},
            "responseJson": {"collection": collection},
            "finalAnswer": "知识库中没有足够依据回答这个问题。",
        }


class InsufficientRagWithMatchesService(EmptyRagQueryService):
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        response = super().run(prompt, collection, agent_id, thread_id, user_id, collected_vars)
        response["vectorMatches"] = [
            {
                "id": "vec_unrelated",
                "nodeId": "retrieve_context",
                "provider": "chroma",
                "collection": collection,
                "title": "安盛天平个人综合住院医疗保险",
                "contentPreview": "这是一段无关的安盛天平条款。",
                "metadata": {},
            }
        ]
        response["finalAnswer"] = "知识库中没有足够依据回答复星联合医疗险的问题。"
        return response


class FakePlannerGenerator:
    def __init__(self, route: str, answer_key: str | None = None, clarifying_question: str | None = None) -> None:
        self.route = route
        self.answer_key = answer_key
        self.clarifying_question = clarifying_question
        self.prompts: list[str] = []
        self.system_prompts: list[str | None] = []

    def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        return {
            "answer": json.dumps(
                {
                    "route": self.route,
                    "confidence": 0.91,
                    "reason": "fake planner decision",
                    "tasks": ["fake_task"],
                    "answer_key": self.answer_key,
                    "needs_user_input": self.route == "clarify",
                    "clarifying_question": self.clarifying_question,
                },
                ensure_ascii=False,
            ),
            "tokens": {},
            "raw": {},
        }


def test_research_graph_delegates_to_rag_service_and_preserves_response() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(service, planner_generator=FakePlannerGenerator("insurance_research"))

    result = graph.run(
        prompt=" 查一下等待期 ",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        user_id="user_1",
        collected_vars={"age": 30},
    )

    assert result["id"] == "run_fake"
    assert result["finalAnswer"] == "ok"
    assert result["nodes"][0]["id"] == "receive_input"
    assert service.calls == [
        {
            "prompt": " 查一下等待期 ",
            "collection": "guides",
            "agent_id": "research-agent",
            "thread_id": "thread_1",
            "user_id": "user_1",
            "collected_vars": {"age": 30},
        }
    ]


def test_research_graph_runs_allowed_cli_command(tmp_path: Path) -> None:
    source_file = tmp_path / "notes.md"
    source_file.write_text("cli marker evidence", encoding="utf-8")
    graph = ResearchAgentGraph(
        EmptyRagQueryService(),
        planner_generator=FakePlannerGenerator("insurance_research"),
        local_source_root=tmp_path,
    )

    result = graph.run(
        prompt="运行命令 rg cli .",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert "cli marker evidence" in result["finalAnswer"]
    assert result["toolCalls"][0]["name"] == "run_cli"
    assert result["toolCalls"][0]["status"] == "succeeded"


def test_research_graph_returns_approval_request_for_risky_cli_command(tmp_path: Path) -> None:
    graph = ResearchAgentGraph(
        EmptyRagQueryService(),
        planner_generator=FakePlannerGenerator("insurance_research"),
        local_source_root=tmp_path,
    )

    result = graph.run(
        prompt="run command rm notes.md",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        collected_vars={"commandMode": "build"},
    )

    assert result["status"] == "awaiting_approval"
    assert result["approvalRequest"]["command"] == "rm notes.md"
    assert result["approvalRequest"]["risk"] == "file_delete"
    assert result["toolCalls"][0]["status"] == "pending"


def test_research_graph_uses_local_file_when_rag_is_empty(tmp_path: Path) -> None:
    source_file = tmp_path / "alpha.md"
    source_file.write_text("AlphaCare 官方资料：等待期为30天。", encoding="utf-8")
    service = EmptyRagQueryService()
    graph = ResearchAgentGraph(
        service,
        planner_generator=FakePlannerGenerator("insurance_research"),
        local_source_root=tmp_path,
        enable_web_search=False,
    )

    result = graph.run(
        prompt="帮我查 AlphaCare 官方资料",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls
    assert "AlphaCare 官方资料" in result["finalAnswer"]
    assert str(source_file) in result["finalAnswer"]
    assert any(call["name"] == "local_search" for call in result["toolCalls"])


def test_research_graph_uses_source_fallback_when_rag_matches_are_unrelated(tmp_path: Path) -> None:
    source_file = tmp_path / "fosun.md"
    source_file.write_text("复星联合健康保险：医疗险产品线索。", encoding="utf-8")
    graph = ResearchAgentGraph(
        InsufficientRagWithMatchesService(),
        planner_generator=FakePlannerGenerator("insurance_research"),
        local_source_root=tmp_path,
        enable_web_search=False,
    )

    result = graph.run(
        prompt="你帮我去复星联合找一款医疗险",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert "复星联合健康保险" in result["finalAnswer"]
    assert str(source_file) in result["finalAnswer"]
    assert any(call["name"] == "local_search" for call in result["toolCalls"])


class FakeEvidenceRegistry:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, prompt: str) -> dict:
        self.calls.append(prompt)
        return {
            "enabled": True,
            "summary": "Matched 1 company source entries and 1 official material candidates.",
            "companyMatches": [{"company": "太平人寿保险有限公司", "sourceTier": "S2_OFFICIAL_SPEC"}],
            "materialMatches": [{"productName": "太平乐享居一号", "sourceTier": "S1_OFFICIAL_PDF"}],
        }


class EmptyEvidenceRegistry:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, prompt: str) -> dict:
        self.calls.append(prompt)
        return {
            "enabled": True,
            "summary": "Matched 0 company source entries and 0 official material candidates.",
            "companyMatches": [],
            "materialMatches": [],
        }


def test_research_graph_adds_evidence_registry_trace_when_available() -> None:
    graph = ResearchAgentGraph(
        FakeRagQueryService(),
        evidence_source_registry=FakeEvidenceRegistry(),
        planner_generator=FakePlannerGenerator("insurance_research"),
    )

    result = graph.run(
        prompt="帮我找太平乐享居一号官方资料",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert result["nodes"][0]["id"] == "load_evidence_sources"
    assert result["events"][0]["nodeId"] == "load_evidence_sources"
    assert result["toolCalls"][0]["name"] == "source_registry_lookup"
    assert result["responseJson"]["evidenceSourceRegistry"]["materialMatches"][0]["sourceTier"] == "S1_OFFICIAL_PDF"


def test_research_graph_answers_identity_question_without_rag_or_evidence_lookup() -> None:
    service = FakeRagQueryService()
    registry = FakeEvidenceRegistry()
    planner = FakePlannerGenerator("direct_answer", answer_key="meta_identity")
    graph = ResearchAgentGraph(service, evidence_source_registry=registry, planner_generator=planner)

    result = graph.run(
        prompt="你好，你是谁",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
        user_id="user_1",
    )

    assert service.calls == []
    assert registry.calls == []
    assert result["status"] == "succeeded"
    assert "保险产品研究 Agent" in result["finalAnswer"]
    assert "知识库中没有足够依据" not in result["finalAnswer"]
    assert result["nodes"][0]["id"] == "entry_planner"
    assert result["responseJson"]["routePlan"]["route"] == "direct_answer"
    assert "用户输入：你好，你是谁" in planner.prompts[0]


def test_research_graph_answers_capability_question_without_rag() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=EmptyEvidenceRegistry(),
        planner_generator=FakePlannerGenerator("capability_answer"),
    )

    result = graph.run(
        prompt="你都能干什么？",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls == []
    assert "项目内的文件检查" in result["finalAnswer"]
    assert "RAG 目前先保留占位" in result["finalAnswer"]
    assert result["responseJson"]["routePlan"]["route"] == "capability_answer"
    assert result["responseJson"]["capabilities"]["matchedTools"]


def test_research_graph_answers_file_capability_from_runtime_manifest() -> None:
    service = FakeRagQueryService()
    planner = FakePlannerGenerator("capability_answer")
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=EmptyEvidenceRegistry(),
        planner_generator=planner,
    )

    result = graph.run(
        prompt="你能检查我本地的文件吗？",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls == []
    assert planner.prompts
    assert result["responseJson"]["routePlan"]["route"] == "capability_answer"
    assert "可以" in result["finalAnswer"]
    assert "本地文件" in result["finalAnswer"]
    assert "确认" in result["finalAnswer"]
    assert "我可以帮你做这些事" not in result["finalAnswer"]
    assert result["responseJson"]["capabilities"]["matchedTools"]


def test_research_graph_passes_entry_planner_system_prompt_to_model() -> None:
    service = FakeRagQueryService()
    planner = FakePlannerGenerator("insurance_research")
    graph = ResearchAgentGraph(service, planner_generator=planner)

    graph.run(
        prompt="查一下等待期",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert planner.system_prompts
    assert planner.system_prompts[0] is not None
    assert "最高优先级分类规则" in planner.system_prompts[0]
    assert "capability_answer" in planner.system_prompts[0]


def test_research_graph_explains_delete_file_capability_as_hitl() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=EmptyEvidenceRegistry(),
        planner_generator=FakePlannerGenerator("capability_answer"),
    )

    result = graph.run(
        prompt="你能删除文件吗？",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls == []
    assert "删除文件" in result["finalAnswer"]
    assert "确认" in result["finalAnswer"]
    assert "特别危险" in result["finalAnswer"]


def test_research_graph_rejects_non_insurance_request_without_rag_when_no_evidence_match() -> None:
    service = FakeRagQueryService()
    registry = EmptyEvidenceRegistry()
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=registry,
        planner_generator=FakePlannerGenerator("out_of_scope", answer_key="boundary_response"),
    )

    result = graph.run(
        prompt="帮我写一篇咖啡店开业文案",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls == []
    assert registry.calls == []
    assert "保险" in result["finalAnswer"]
    assert "知识库中没有足够依据" not in result["finalAnswer"]
    assert result["responseJson"]["routePlan"]["route"] == "out_of_scope"


def test_research_graph_routes_product_name_with_evidence_match_to_rag() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=FakeEvidenceRegistry(),
        planner_generator=FakePlannerGenerator("insurance_research"),
    )

    result = graph.run(
        prompt="太平乐享居一号",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls[0]["prompt"] == "太平乐享居一号"
    assert result["finalAnswer"] == "ok"


def test_research_graph_returns_planner_clarifying_question_without_rag() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=FakeEvidenceRegistry(),
        planner_generator=FakePlannerGenerator(
            "clarify",
            clarifying_question="请告诉我产品名称，或上传需要分析的保险条款。",
        ),
    )

    result = graph.run(
        prompt="帮我分析一下",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread_1",
    )

    assert service.calls == []
    assert result["finalAnswer"] == "请告诉我产品名称，或上传需要分析的保险条款。"
    assert result["responseJson"]["routePlan"]["route"] == "clarify"


def test_research_graph_resolves_followup_prompt_with_thread_memory(tmp_path: Path) -> None:
    memory = ConversationMemoryStore(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    memory.initialize()
    session_id = memory.create_session(
        user_id="user-1",
        thread_id="thread-1",
        title="Product Alpha",
        task_type="conversation",
    )
    memory.add_message(session_id=session_id, role="user", content="Please research Product Alpha.")
    memory.add_message(session_id=session_id, role="assistant", content="Product Alpha has a 90 day waiting period.")
    memory.upsert_thread_summary(
        user_id="user-1",
        thread_id="thread-1",
        summary="The active product is Product Alpha.",
        latest_session_id=session_id,
        final_answer="Product Alpha has a 90 day waiting period.",
    )
    service = FakeRagQueryService()
    registry = FakeEvidenceRegistry()
    graph = ResearchAgentGraph(
        service,
        evidence_source_registry=registry,
        memory_store=memory,
        planner_generator=FakePlannerGenerator("insurance_research"),
    )

    result = graph.run(
        prompt="continue the waiting period",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread-1",
        user_id="user-1",
    )

    assert service.calls[0]["prompt"] != "continue the waiting period"
    assert "Product Alpha" in service.calls[0]["prompt"]
    assert registry.calls[0] == service.calls[0]["prompt"]
    assert result["prompt"] == "continue the waiting period"
    assert result["responseJson"]["memory"]["resolvedPrompt"] == service.calls[0]["prompt"]


def test_research_graph_saves_direct_response_to_thread_memory(tmp_path: Path) -> None:
    memory = ConversationMemoryStore(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    memory.initialize()
    graph = ResearchAgentGraph(
        FakeRagQueryService(),
        memory_store=memory,
        planner_generator=FakePlannerGenerator(
            "clarify",
            clarifying_question="Which product should I research?",
        ),
    )

    result = graph.run(
        prompt="help me research",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread-1",
        user_id="user-1",
    )

    messages = memory.get_recent_thread_messages("user-1", "thread-1", limit=10)
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "Which product should I research?"
    assert result["responseJson"]["memory"]["rememberedContext"]["recent_messages"] == []


def test_research_graph_does_not_rewrite_standalone_question_with_memory(tmp_path: Path) -> None:
    memory = ConversationMemoryStore(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    memory.initialize()
    session_id = memory.create_session(
        user_id="user-1",
        thread_id="thread-1",
        title="Product Alpha",
        task_type="conversation",
    )
    memory.add_message(session_id=session_id, role="assistant", content="Product Alpha has a 90 day waiting period.")
    memory.upsert_thread_summary(
        user_id="user-1",
        thread_id="thread-1",
        summary="The active product is Product Alpha.",
        latest_session_id=session_id,
        final_answer="Product Alpha has a 90 day waiting period.",
    )
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(
        service,
        memory_store=memory,
        planner_generator=FakePlannerGenerator("insurance_research"),
    )

    result = graph.run(
        prompt="benefit amount for Product Beta",
        collection="guides",
        agent_id="research-agent",
        thread_id="thread-1",
        user_id="user-1",
    )

    assert service.calls[0]["prompt"] == "benefit amount for Product Beta"
    assert result["responseJson"]["memory"]["resolvedPrompt"] == "benefit amount for Product Beta"
