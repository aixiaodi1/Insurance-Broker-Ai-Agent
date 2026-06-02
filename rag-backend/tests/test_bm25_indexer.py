from app.retrieval.bm25_indexer import MemoryBM25Indexer, rrf_fusion, BM25Doc


def _make_vector_match(id_str: str, text: str) -> dict:
    return {"id": id_str, "contentPreview": text, "metadata": {"chunk_index": 0}}


def _make_bm25_match(id_str: str, text: str) -> dict:
    return {"id": id_str, "contentPreview": text, "metadata": {}, "collection": "default", "bm25_rank": 0, "bm25_score": 1.0}


class TestMemoryBM25Indexer:
    def test_rebuild_and_search(self) -> None:
        indexer = MemoryBM25Indexer()
        chunks = [
            BM25Doc(id="d1", text="本合同条款适用于所有保险合同", collection="default"),
            BM25Doc(id="d2", text="理赔申请人应在事故发生后及时通知保险公司", collection="default"),
            BM25Doc(id="d3", text="保险责任免除条款详见附件", collection="default"),
        ]
        indexer.rebuild(chunks)
        results = indexer.search("合同条款")
        assert len(results) > 0
        assert any("合同" in r.get("contentPreview", "") for r in results)
        assert all("id" in r for r in results)

    def test_search_returns_empty_when_no_docs(self) -> None:
        indexer = MemoryBM25Indexer()
        assert indexer.search("test") == []

    def test_add_and_search(self) -> None:
        indexer = MemoryBM25Indexer()
        indexer.add(BM25Doc(id="d1", text="保险理赔流程包括报案、定损、理赔", collection="default"))
        results = indexer.search("理赔流程")
        assert len(results) > 0
        assert "理赔" in results[0].get("contentPreview", "")

    def test_add_string_backward_compat(self) -> None:
        indexer = MemoryBM25Indexer()
        indexer.add("unique_one_doc")
        results = indexer.search("unique_one")
        assert len(results) >= 1

    def test_remove_by_id(self) -> None:
        indexer = MemoryBM25Indexer()
        indexer.add(BM25Doc(id="d1", text="unique removal target text"))
        assert len(indexer.search("removal")) > 0
        indexer.remove_by_id("d1")
        assert len(indexer.search("removal")) == 0

    def test_collection_isolation(self) -> None:
        indexer = MemoryBM25Indexer()
        indexer.rebuild([
            BM25Doc(id="d1", text="保险合同条款", collection="policy_a"),
            BM25Doc(id="d2", text="健康险理赔流程", collection="policy_b"),
        ])
        all_results = indexer.search("保险", top_n=10)
        assert len(all_results) == 2
        policy_a_results = indexer.search("保险", top_n=10, collection="policy_a")
        assert len(policy_a_results) == 1
        assert policy_a_results[0]["collection"] == "policy_a"

    def test_concurrent_add_and_search(self) -> None:
        import concurrent.futures

        indexer = MemoryBM25Indexer()
        indexer.rebuild([BM25Doc(id="d0", text="initial doc")])

        def add_worker(text: str) -> None:
            indexer.add(text)

        def search_worker(query: str) -> list[dict]:
            return indexer.search(query)

        texts = [f"doc {i}: insurance claim条款" for i in range(10)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as exe:
            add_futures = [exe.submit(add_worker, t) for t in texts]
            search_futures = [exe.submit(search_worker, "claim") for _ in range(10)]
            concurrent.futures.wait(add_futures + search_futures)

        results = indexer.search("claim")
        assert len(results) >= 1


class TestRrfFusion:
    def test_fuses_vector_and_bm25_results(self) -> None:
        vector = [
            _make_vector_match("a", "关于保险合同"),
            _make_vector_match("b", "理赔流程说明"),
        ]
        bm25 = [
            _make_bm25_match("a", "关于保险合同"),
            _make_bm25_match("c", "免责条款说明"),
        ]
        fused = rrf_fusion(vector, bm25, k=60)
        assert len(fused) >= 2
        assert any("合同" in item["contentPreview"] for item in fused)

    def test_deduplicates_by_id(self) -> None:
        vector = [
            _make_vector_match("a", "duplicate text"),
            _make_vector_match("b", "other text"),
        ]
        bm25 = [
            _make_bm25_match("a", "duplicate text"),
        ]
        fused = rrf_fusion(vector, bm25, k=60)
        ids = [item["id"] for item in fused]
        assert ids.count("a") == 1

    def test_returns_sorted_by_score(self) -> None:
        vector = [
            _make_vector_match("a", "low relevance text"),
            _make_vector_match("b", "high relevance text"),
        ]
        bm25 = [
            _make_bm25_match("b", "high relevance text"),
        ]
        fused = rrf_fusion(vector, bm25, k=1)
        assert fused[0]["id"] == "b"

    def test_tracks_rrf_debug(self) -> None:
        vector = [
            _make_vector_match("a", "关于保险合同"),
        ]
        bm25 = [
            _make_bm25_match("b", "免责条款说明"),
        ]
        fused = rrf_fusion(vector, bm25, k=60)
        assert "rrf_debug" in fused[0]
        assert fused[0]["rrf_debug"]["vector_rank"] == 0
        assert fused[1]["rrf_debug"]["bm25_rank"] == 0

    def test_handles_empty_inputs(self) -> None:
        assert rrf_fusion([], []) == []
        assert rrf_fusion([_make_vector_match("a", "text")], []) != []
        assert len(rrf_fusion([], [_make_bm25_match("b", "text")])) == 1
