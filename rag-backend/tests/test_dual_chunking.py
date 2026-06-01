from app.infrastructure.chunkers.document_aware import DocumentAwareChunker


class TestDualChunking:
    def test_dual_split_returns_parents_and_children(self) -> None:
        text = "第一段内容。" * 100 + "第二段内容。" * 100
        chunker = DocumentAwareChunker(chunk_size=300, chunk_overlap=30)
        parents, children = chunker.dual_split(text, parent_chunk_size=1500)
        assert len(parents) > 0
        assert len(children) > 0
        assert all(isinstance(c.text, str) for c in parents)
        assert all(isinstance(c.text, str) for c in children)

    def test_parent_chunks_are_larger_than_children(self) -> None:
        text = "测试段落。" * 200
        chunker = DocumentAwareChunker(chunk_size=300, chunk_overlap=30)
        parents, children = chunker.dual_split(text, parent_chunk_size=1500)
        if parents and children:
            avg_parent = sum(len(c.text) for c in parents) / len(parents)
            avg_child = sum(len(c.text) for c in children) / len(children)
            assert avg_parent > avg_child

    def test_dual_split_handles_short_text(self) -> None:
        text = "这是一段很短的文本。"
        chunker = DocumentAwareChunker(chunk_size=300, chunk_overlap=30)
        parents, children = chunker.dual_split(text)
        assert len(parents) >= 1
        assert len(children) >= 1

    def test_dual_split_handles_insurance_clause(self) -> None:
        text = (
            "第一条 保险责任\n"
            "在保险期间内，被保险人因意外事故导致身故或伤残的，保险公司承担赔偿责任。\n"
            "第二条 责任免除\n"
            "因下列原因造成的损失，保险人不承担赔偿责任：\n"
            "（一）投保人的故意行为；\n"
            "（二）被保险人自致伤害或自杀。\n"
        )
        chunker = DocumentAwareChunker(chunk_size=300, chunk_overlap=30)
        parents, children = chunker.dual_split(text)
        assert len(parents) >= 1
        assert len(children) >= 1
