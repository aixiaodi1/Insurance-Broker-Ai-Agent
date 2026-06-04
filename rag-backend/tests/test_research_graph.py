from app.agents.research_graph import ResearchAgentGraph


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


def test_research_graph_delegates_to_rag_service_and_preserves_response() -> None:
    service = FakeRagQueryService()
    graph = ResearchAgentGraph(service)

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


class FakeEvidenceRegistry:
    def query(self, prompt: str) -> dict:
        return {
            "enabled": True,
            "summary": "Matched 1 company source entries and 1 official material candidates.",
            "companyMatches": [{"company": "太平人寿保险有限公司", "sourceTier": "S2_OFFICIAL_SPEC"}],
            "materialMatches": [{"productName": "太平乐享居一号", "sourceTier": "S1_OFFICIAL_PDF"}],
        }


def test_research_graph_adds_evidence_registry_trace_when_available() -> None:
    graph = ResearchAgentGraph(FakeRagQueryService(), evidence_source_registry=FakeEvidenceRegistry())

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
