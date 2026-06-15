from app.agents.nodes.memory_nodes import save_memory_and_audit
from app.memory.sqlite_memory import SQLiteMemory


class FakeGenerator:
    def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
        return {
            "answer": """
            {
              "facts": [
                {
                  "namespace": "user:user-1:profile",
                  "key": "preferred_output_style",
                  "value": {"style": "table"},
                  "confidence": 0.88
                }
              ],
              "project_memories": [
                {
                  "kind": "product_alias",
                  "key": "alpha",
                  "value": {"canonical": "Alpha Product"}
                }
              ],
              "evidence_memories": [
                {
                  "product_name": "Alpha Product",
                  "title": "Alpha official PDF",
                  "source_url": "https://example.com/alpha.pdf",
                  "source_tier": "S1",
                  "chunk_id": "alpha-001",
                  "file_hash": "hash-alpha"
                }
              ]
            }
            """
        }


def test_save_memory_and_audit_writes_llm_extracted_memory(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:thread-a", "alpha", "research")
    state = {
        "user_id": "user-1",
        "thread_id": "user-1:thread-a",
        "session_id": session_id,
        "user_input": "I prefer tables when researching alpha.",
        "user_level": "novice",
        "product_name": "Alpha Product",
        "aliases": ["alpha"],
        "rag_citations": [],
        "evidence_score": {"total": 20},
        "stop_reasons": [],
        "final_summary": "Alpha answer",
    }

    result = save_memory_and_audit(state, memory, memory_extractor=FakeGenerator())
    recalled = memory.recall_memory("user-1", "user-1:thread-a", "alpha")

    assert result["memory_extraction"]["ok"] is True
    assert any(item["key"] == "preferred_output_style" for item in recalled["facts"])
    assert any(item["key"] == "alpha" for item in recalled["project_memories"])
    assert any(item["chunk_id"] == "alpha-001" for item in recalled["evidence_memories"])


class BadGenerator:
    def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
        return {"answer": "not json"}


def test_save_memory_and_audit_keeps_running_when_memory_extraction_fails(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    session_id = memory.create_session("user-1", "user-1:thread-a", "alpha", "research")
    state = {
        "user_id": "user-1",
        "thread_id": "user-1:thread-a",
        "session_id": session_id,
        "user_input": "alpha",
        "user_level": "novice",
        "product_name": "Alpha Product",
        "aliases": [],
        "rag_citations": [],
        "evidence_score": {"total": 20},
        "stop_reasons": [],
        "final_summary": "Alpha answer",
    }

    result = save_memory_and_audit(state, memory, memory_extractor=BadGenerator())

    assert result["memory_extraction"]["ok"] is False
    assert memory.get_thread_summary("user-1:thread-a")["final_summary"] == "Alpha answer"
