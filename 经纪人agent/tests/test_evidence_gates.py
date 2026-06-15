from app.gates.evidence_gates import evidence_gate, verify_before_rag_gate
from app.gates.permission_gates import secret_write_deny_gate


def test_evidence_gate_blocks_formal_report_without_official_sources():
    decision = evidence_gate({"official_sources": [], "rag_citations": []})
    assert decision["allowed"] is False
    assert decision["route"] == "generate_user_friendly_summary"


def test_verify_before_rag_gate_blocks_invalid_pdf():
    decision = verify_before_rag_gate({"pdf_assets": [{"is_valid_pdf": False}]})
    assert decision["allowed"] is False


def test_secret_write_deny_gate_blocks_env_files():
    decision = secret_write_deny_gate(".env")
    assert decision["allowed"] is False
