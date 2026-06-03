import json

from app.domain import CalculationRecord, QueryIntent
from app.services.rag_query_service import RagQueryService
from app.services.thread_state_store import ThreadStateStore
from app.services.intent_classifier import classify_intent


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class FakeVectorStore:
    def __init__(self, matches: list[dict] | None = None) -> None:
        self._matches = matches or [
            {
                "id": "doc_1:0",
                "document": (
                    "保险责任：在保险期间内，被保险人因意外或等待期后因疾病"
                    "在二级及以上公立医院住院治疗的，对其实际发生的医疗费用，"
                    "在扣除免赔额后按约定比例进行赔付。年度限额 200 万。"
                    "免赔额 500 元。赔付比例 100%。"
                ),
                "metadata": {"source_file": "policy.txt", "chunk_index": 0, "section_title": "保险责任"},
                "distance": 0.2,
            },
        ]

    def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5) -> list[dict]:
        return self._matches


class FakeReranker:
    def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[dict]:
        return [{"index": 0, "document": documents[0], "score": 0.99}]


class FakeGenerator:
    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []
        self.system_prompts: list[str | None] = []

    def _default_vars(self) -> dict:
        return {
            "medical_expense": None, "eligible_expense": None,
            "deductible": None, "reimbursement_ratio": None,
            "social_insurance_used": None, "annual_limit": None,
            "single_limit": None, "hospital_level": None,
            "disease_name": None, "claim_type": None,
        }

    def _parse_user_vars_from_prompt(self, prompt: str) -> dict:
        """Extract user-provided variables from the prompt text."""
        vars = self._default_vars()
        idx = prompt.find("用户输入：")
        if idx == -1:
            return vars
        user_query = prompt[idx + 5:].strip()

        import re

        # "医疗费用" or "6万多" or "6万"
        if "花了" in user_query or "医疗费用" in user_query:
            m = re.search(r"(\d+(?:\.\d+)?)\s*万", user_query)
            if m:
                val = float(m.group(1)) * 10000
            else:
                m = re.search(r"(\d+(?:\.\d+)?)", user_query)
                val = float(m.group(1)) if m else 60000
            vars["medical_expense"] = val
            vars["eligible_expense"] = val

        if "免赔额" in user_query:
            m = re.search(r"免赔额\s*(\d+(?:\.\d+)?)", user_query)
            if m:
                vars["deductible"] = float(m.group(1))
            else:
                vars["deductible"] = 500

        if "比例" in user_query or "%" in user_query:
            vars["reimbursement_ratio"] = 1.0

        return {k: v for k, v in vars.items() if v is not None}

    def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
        self.call_count += 1
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)

        # Call 1: rule extraction
        if "知识库资料" in prompt and ("抽取" in prompt or "rule_type" in prompt.lower()):
            return {
                "answer": json.dumps(
                    [
                        {
                            "rule_type": "medical_reimbursement",
                            "formula": "(医疗费用 - 免赔额) × 赔付比例",
                            "formula_expr": "(eligible_expense - deductible) * reimbursement_ratio",
                            "required_vars": ["eligible_expense", "deductible", "reimbursement_ratio"],
                            "optional_vars": ["social_insurance_used"],
                            "limits": {"annual_limit": 2000000, "single_limit": None, "notes": ""},
                            "evidence": [{"chunk_id": "doc_1:0", "text": "扣除免赔额后按约定比例赔付"}],
                        }
                    ],
                    ensure_ascii=False,
                ),
                "tokens": {"prompt": 200, "completion": 80, "total": 280},
                "raw": {},
            }

        # Call 2: var extraction
        if "用户输入" in prompt and ("提取" in prompt or "medical_expense" in prompt.lower()):
            extracted = self._parse_user_vars_from_prompt(prompt)
            return {
                "answer": json.dumps(extracted, ensure_ascii=False),
                "tokens": {"prompt": 150, "completion": 40, "total": 190},
                "raw": {},
            }

        # Call 3+: final answer generation
        return {
            "answer": "根据条款，赔付金额计算如下：[1]",
            "tokens": {"prompt": 300, "completion": 50, "total": 350},
            "raw": {},
        }


class FakeRepository:
    def __init__(self) -> None:
        self.records: list[CalculationRecord] = []
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def get_parent_chunk(self, parent_id: str) -> str | None:
        return None

    def create_calculation_record(
        self,
        run_id: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        collection: str | None = None,
        active_document_id: str | None = None,
        intent: str | None = None,
        formula: str | None = None,
        input_vars: dict | None = None,
        missing_vars: list[str] | None = None,
        result: dict | None = None,
        rule_refs: list[dict] | None = None,
        answer: str | None = None,
    ) -> CalculationRecord:
        record = CalculationRecord(
            id=f"calc_{len(self.records) + 1}",
            run_id=run_id,
            thread_id=thread_id,
            user_id=user_id,
            collection=collection,
            active_document_id=active_document_id,
            intent=intent,
            formula=formula,
            input_vars_json=json.dumps(input_vars, ensure_ascii=False) if input_vars else None,
            missing_vars_json=json.dumps(missing_vars, ensure_ascii=False) if missing_vars else None,
            result_json=json.dumps(result, ensure_ascii=False) if result else None,
            rule_refs_json=json.dumps(rule_refs, ensure_ascii=False) if rule_refs else None,
            answer=answer,
            created_at="2026-06-02T19:00:00+09:00",
        )
        self.records.append(record)
        return record


class FakeThreadStateStore:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def _key(self, user_id: str, thread_id: str, collection: str) -> str:
        return f"thread_state:{user_id}:{thread_id}:{collection}"

    def get_state(self, user_id: str, thread_id: str, collection: str) -> dict | None:
        return self._store.get(self._key(user_id, thread_id, collection))

    def save_state(self, user_id: str, thread_id: str, collection: str, state: dict) -> None:
        self._store[self._key(user_id, thread_id, collection)] = state

    def delete_state(self, user_id: str, thread_id: str, collection: str) -> None:
        self._store.pop(self._key(user_id, thread_id, collection), None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_service(
    generator: FakeGenerator | None = None,
    repository: FakeRepository | None = None,
    state_store: FakeThreadStateStore | None = None,
    vector_matches: list[dict] | None = None,
) -> RagQueryService:
    return RagQueryService(
        embedder=FakeEmbedder(),
        vector_store=FakeVectorStore(matches=vector_matches),
        reranker=FakeReranker(),
        generator=generator or FakeGenerator(),
        repository=repository or FakeRepository(),
        retrieval_top_k=20,
        rerank_top_k=5,
        embedding_dimension=2,
        state_store=state_store or FakeThreadStateStore(),
        redis_url="redis://localhost:6379/0",
    )


def extract_calculation_fields(response: dict) -> dict:
    return {
        k: response.get(k)
        for k in (
            "intent", "activeDocumentId", "activeProductName",
            "collectedVars", "missingVars", "pendingCalculation",
            "calculation", "stateId",
        )
    }


# ---------------------------------------------------------------------------
# Case 1: First round — missing variables
# ---------------------------------------------------------------------------

def test_case1_first_round_missing_vars() -> None:
    gen = FakeGenerator()
    repo = FakeRepository()
    store = FakeThreadStateStore()
    service = make_service(generator=gen, repository=repo, state_store=store)

    result = service.run(
        prompt="住院花了6万多，能赔多少？",
        collection="million_medical",
        agent_id="research-agent",
        thread_id="thread_001",
        user_id="user_001",
    )

    assert result["status"] == "succeeded"
    assert result["intent"] == "claim_calculation"

    fields = extract_calculation_fields(result)
    assert fields["pendingCalculation"] is True

    cv = fields["collectedVars"]
    assert isinstance(cv, dict)
    assert cv.get("medical_expense") == 60000 or cv.get("eligible_expense") == 60000

    mv = fields.get("missingVars")
    assert mv is not None
    assert len(mv) > 0
    assert "deductible" in mv or "reimbursement_ratio" in mv

    assert fields["stateId"] is not None

    assert repo.records
    record = repo.records[0]
    assert record.intent == "claim_calculation"
    assert record.missing_vars_json is not None

    saved = store.get_state("user_001", "thread_001", "million_medical")
    assert saved is not None
    assert saved.get("pending_intent") == "claim_calculation"


# ---------------------------------------------------------------------------
# Case 2: Second round — add deductible, still missing
# ---------------------------------------------------------------------------

def test_case2_second_round_add_deductible() -> None:
    gen = FakeGenerator()
    repo = FakeRepository()
    store = FakeThreadStateStore()

    previous_state = {
        "thread_id": "thread_002",
        "user_id": "user_001",
        "collection": "million_medical",
        "active_document_id": "doc_million_medical",
        "active_product_name": None,
        "pending_intent": "claim_calculation",
        "collected_vars": {"medical_expense": 60000},
        "missing_vars": ["deductible", "reimbursement_ratio"],
        "rule_refs": [{"chunk_id": "doc_1:0", "text": "扣除免赔额后按约定比例赔付"}],
        "pending_calculation": True,
    }
    store.save_state("user_001", "thread_002", "million_medical", previous_state)

    service = make_service(generator=gen, repository=repo, state_store=store)

    result = service.run(
        prompt="免赔额500",
        collection="million_medical",
        agent_id="research-agent",
        thread_id="thread_002",
        user_id="user_001",
    )

    assert result["status"] == "succeeded"
    assert result["intent"] == "claim_calculation"

    fields = extract_calculation_fields(result)
    assert fields["pendingCalculation"] is True

    cv = fields["collectedVars"]
    assert cv.get("medical_expense") == 60000

    mv = fields.get("missingVars", [])
    assert "reimbursement_ratio" in mv

    updated = store.get_state("user_001", "thread_002", "million_medical")
    assert updated is not None
    assert "deductible" in updated.get("collected_vars", {})

    assert repo.records


# ---------------------------------------------------------------------------
# Case 3: Third round — complete vars, got calculation
# ---------------------------------------------------------------------------

def test_case3_complete_vars_got_calculation() -> None:
    class CompleteVarGenerator(FakeGenerator):
        def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
            self.call_count += 1
            self.prompts.append(prompt)
            self.system_prompts.append(system_prompt)

            # rule extraction
            if "知识库资料" in prompt and "rule_type" in prompt.lower():
                return {
                    "answer": json.dumps(
                        [
                            {
                                "rule_type": "medical_reimbursement",
                                "formula": "(医疗费用 - 免赔额) × 赔付比例",
                                "formula_expr": "(eligible_expense - deductible) * reimbursement_ratio",
                                "required_vars": ["eligible_expense", "deductible", "reimbursement_ratio"],
                                "optional_vars": [],
                                "limits": {"annual_limit": 2000000, "single_limit": None, "notes": ""},
                                "evidence": [{"chunk_id": "doc_1:0", "text": "扣除免赔额后按约定比例赔付"}],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    "tokens": {"prompt": 200, "completion": 80, "total": 280},
                    "raw": {},
                }

            # var extraction
            if "用户输入" in prompt and "medical_expense" in prompt.lower():
                extracted = self._parse_user_vars_from_prompt(prompt)
                return {
                    "answer": json.dumps(extracted, ensure_ascii=False),
                    "tokens": {"prompt": 150, "completion": 40, "total": 190},
                    "raw": {},
                }

            return {
                "answer": "计算结果：(60000 - 500) × 100% = 59500 元",
                "tokens": {"prompt": 300, "completion": 50, "total": 350},
                "raw": {},
            }

    gen = CompleteVarGenerator()
    repo = FakeRepository()
    store = FakeThreadStateStore()
    service = make_service(generator=gen, repository=repo, state_store=store)

    result = service.run(
        prompt="住院花了6万多，免赔额500，赔付比例100%",
        collection="million_medical",
        agent_id="research-agent",
        thread_id="thread_003",
        user_id="user_001",
    )

    assert result["status"] == "succeeded"
    assert result["intent"] == "claim_calculation"

    fields = extract_calculation_fields(result)
    assert fields["pendingCalculation"] is False

    cv = fields["collectedVars"]
    assert cv.get("medical_expense") == 60000
    assert cv.get("deductible") == 500
    assert cv.get("reimbursement_ratio") == 1.0

    mv = fields.get("missingVars")
    assert mv is None or len(mv) == 0

    calc = fields.get("calculation")
    assert calc is not None
    assert calc.get("formula_expr") == "(eligible_expense - deductible) * reimbursement_ratio"
    assert "59500" in str(calc.get("result"))

    assert repo.records
    record = repo.records[0]
    assert record.result_json is not None
    assert "59500" in record.result_json


# ---------------------------------------------------------------------------
# Case 4: Different threads — no cross-contamination
# ---------------------------------------------------------------------------

def test_case4_different_threads_no_crosstalk() -> None:
    gen = FakeGenerator()
    repo = FakeRepository()
    store = FakeThreadStateStore()

    store.save_state("user_001", "thread_a", "default", {
        "collected_vars": {"medical_expense": 60000},
        "missing_vars": ["deductible"],
        "pending_calculation": True,
        "pending_intent": "claim_calculation",
    })

    service = make_service(generator=gen, repository=repo, state_store=store)

    result_a = service.run(
        prompt="免赔额500",
        collection="default",
        agent_id="research-agent",
        thread_id="thread_a",
        user_id="user_001",
    )
    result_b = service.run(
        prompt="住院花了6万多，能赔多少？",
        collection="default",
        agent_id="research-agent",
        thread_id="thread_b",
        user_id="user_001",
    )

    state_a = store.get_state("user_001", "thread_a", "default")
    state_b = store.get_state("user_001", "thread_b", "default")

    assert state_a is not None
    assert state_b is not None

    cv_a = state_a.get("collected_vars", {})
    cv_b = state_b.get("collected_vars", {})

    assert cv_a.get("deductible") == 500 or "deductible" in cv_a
    assert cv_b.get("deductible") is None or "deductible" not in cv_b


# ---------------------------------------------------------------------------
# Case 5: Different collections — no cross-contamination
# ---------------------------------------------------------------------------

def test_case5_different_collections_no_crosstalk() -> None:
    gen = FakeGenerator()
    repo = FakeRepository()
    store = FakeThreadStateStore()

    store.save_state("user_001", "thread_x", "product_a", {
        "active_document_id": "doc_product_a",
        "collected_vars": {"medical_expense": 100000},
        "missing_vars": ["deductible"],
        "pending_calculation": True,
        "pending_intent": "claim_calculation",
    })
    store.save_state("user_001", "thread_x", "product_b", {
        "active_document_id": "doc_product_b",
        "collected_vars": {"deductible": 1000},
        "missing_vars": ["medical_expense"],
        "pending_calculation": True,
        "pending_intent": "claim_calculation",
    })

    gen_a = FakeGenerator()
    gen_b = FakeGenerator()
    repo_a = FakeRepository()
    repo_b = FakeRepository()

    service_a = make_service(generator=gen_a, repository=repo_a, state_store=store)
    service_b = make_service(generator=gen_b, repository=repo_b, state_store=store)

    result_a = service_a.run(
        prompt="免赔额是多少？",
        collection="product_a",
        agent_id="research-agent",
        thread_id="thread_x",
        user_id="user_001",
    )
    result_b = service_b.run(
        prompt="医疗费用多少？",
        collection="product_b",
        agent_id="research-agent",
        thread_id="thread_x",
        user_id="user_001",
    )

    state_a = store.get_state("user_001", "thread_x", "product_a")
    state_b = store.get_state("user_001", "thread_x", "product_b")

    assert state_a["active_document_id"] == "doc_product_a"
    assert state_b["active_document_id"] == "doc_product_b"
    assert state_a["collected_vars"].get("deductible") is not None or "deductible" in state_a["collected_vars"]
    assert state_b["collected_vars"].get("medical_expense") is not None or "medical_expense" in state_b["collected_vars"]


# ---------------------------------------------------------------------------
# Calculator unit test
# ---------------------------------------------------------------------------

def test_calculator_basic() -> None:
    from app.services.calculator import calc_reimbursement

    result = calc_reimbursement(expense=60000, deductible=500, ratio=1.0)
    assert float(result["result"]) == 59500.00
    assert "59500" in result["explanation"]
    assert "(60000 - 500) × 1" in result["formula"]


def test_calculator_with_limit() -> None:
    from app.services.calculator import calc_reimbursement

    result = calc_reimbursement(expense=3000000, deductible=500, ratio=1.0, limit=2000000)
    assert float(result["result"]) == 2000000.00


def test_calculator_expense_less_than_deductible() -> None:
    from app.services.calculator import calc_reimbursement

    result = calc_reimbursement(expense=200, deductible=500, ratio=1.0)
    assert float(result["result"]) == 0.00


# ---------------------------------------------------------------------------
# Intent classifier test for CLAIM_CALCULATION
# ---------------------------------------------------------------------------

def test_intent_classifies_claim_calculation() -> None:
    assert classify_intent("住院花了6万多，能赔多少？") == QueryIntent.CLAIM_CALCULATION
    assert classify_intent("医疗费花了5万元，帮我算算能赔多少") == QueryIntent.CLAIM_CALCULATION
    assert classify_intent("能赔多少？") == QueryIntent.CLAIM_CALCULATION
